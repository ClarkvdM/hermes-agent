"""CLI subprocess contracts with isolated homes and synthetic fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_mocked_provider_selection_json_matches_context(tmp_path, monkeypatch, capsys):
    from hermes_cli.skills_select_cli import main
    from hermes_cli import skills_select_provider as provider
    root = fixture_skills(tmp_path)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'synthetic-key')
    payloads_seen = []
    def score(payloads, key):
        payloads_seen.extend(payloads)
        assert key == 'synthetic-key'
        return {k: {'score': 8.25, 'confidence': .75} for p in payloads for k in p['questions']}, {'input_tokens': 12, 'output_tokens': 2}
    monkeypatch.setattr(provider, 'score_payloads', score)
    args = ['review', '--skills-dir', str(root), '--allow-upload']
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['selected'][0]['score'] == 8.25
    assert data['total_score'] == 8.25
    assert data['target_reached'] is False
    assert data['usage'] == {'input_tokens': 12, 'output_tokens': 2}
    assert main(args + ['--format', 'context']) == 0
    assert capsys.readouterr().out == data['context']
    assert 'PRIVATE BODY' not in json.dumps(payloads_seen)


@pytest.mark.parametrize('target', ['18', '8'])
def test_max_skills_caps_qualifying_selection_and_reports_reasons(tmp_path, monkeypatch, capsys, target):
    from hermes_cli.skills_select_cli import main
    from hermes_cli import skills_select_provider as provider
    root = tmp_path / 'skills'
    for name, body in [('a', 'huge ' * 3000), ('b', 'short'), ('c', 'short'), ('d', 'short')]:
        path = root / name / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(f'---\nname: {name}\ndescription: Useful\n---\n{body}', encoding='utf-8')
    def score(payloads, key):
        return {f'skill_{i:05d}': {'score': value, 'confidence': .75}
                for i, value in enumerate([9, 8, 7, 1])}, {}
    monkeypatch.setattr(provider, 'score_payloads', score)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'synthetic-key')
    args = ['review', '--skills-dir', str(root), '--allow-upload', '--token-budget', '100',
            '--target-score', target, '--max-skills', '1']
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert [s['name'] for s in result['selected']] == ['b']
    assert result['max_skills'] == result['selected_count'] == 1
    assert [s['reason'] for s in result['skipped']] == ['token_budget', 'max_skills', 'below_minimum']
    assert result['target_reached'] is (target == '8')
    assert result['token_count'] <= 100


@pytest.mark.parametrize('cap', ['0', '-1', '1.5'])
def test_max_skills_rejects_nonpositive_or_noninteger_cap(tmp_path, cap):
    proc = run_cli(tmp_path, 'review', '--skills-dir', str(fixture_skills(tmp_path)),
                   '--dry-run', '--max-skills', cap)
    assert proc.returncode == 2
    assert '--max-skills' in proc.stderr


def test_bundled_inventory_dry_run_offline(tmp_path):
    from hermes_cli.skills_select import discover_skills
    from hermes_cli.skills_select_provider import build_payloads
    skills, skipped = discover_skills(REPO / 'skills')
    proc = run_cli(tmp_path, 'Review a software change', '--skills-dir', str(REPO / 'skills'), '--dry-run')
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data['candidate_count'] == len(skills) > 0
    assert data['payloads'] == build_payloads(skills, 'Review a software change')
    assert data['skipped'] == skipped


def test_profile_default_and_context_file(tmp_path):
    root = fixture_skills(tmp_path)
    import shutil
    home = tmp_path / 'home' / 'profile'
    shutil.copytree(root, home / 'skills')
    context = tmp_path / 'context.txt'
    context.write_text('Recent synthetic context.', encoding='utf-8')
    proc = run_cli(tmp_path, 'review', '--context-file', str(context), '--dry-run')
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['payloads'][0]['state']['recent_context'] == 'Recent synthetic context.'


def test_named_profile_and_prompt_flag_are_independent(tmp_path):
    import shutil
    root = fixture_skills(tmp_path)
    home = tmp_path / 'home' / 'profile' / 'profiles' / 'demo'
    shutil.copytree(root, home / 'skills')
    (home / 'config.yaml').write_text('{}\n', encoding='utf-8')
    proc = run_cli(tmp_path, '-p', 'review', '--dry-run', global_args=('--profile', 'demo'))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['candidate_count'] == 1
    assert json.loads(proc.stdout)['payloads'][0]['state']['task'] == 'review'


def test_dotenv_is_not_a_key_source(tmp_path):
    root = fixture_skills(tmp_path)
    home = tmp_path / 'home' / 'profile'
    home.mkdir(parents=True)
    (home / '.env').write_text('TYPESAFE_API_KEY=synthetic-key\n', encoding='utf-8')
    proc = run_cli(tmp_path, 'review', '--skills-dir', str(root), '--allow-upload')
    assert proc.returncode == 2
    assert 'Set TYPESAFE_API_KEY' in proc.stderr
    assert 'synthetic-key' not in proc.stdout + proc.stderr


@pytest.mark.parametrize('args', [[], ['x', '-p', 'y'], ['x', '--minimum-score', 'nan'],
    ['x', '--target-score', '0'], ['x', '--token-budget', '-1'], ['x', '--format', 'context']])
def test_invalid_arguments(tmp_path, args):
    proc = run_cli(tmp_path, *args, '--skills-dir', str(fixture_skills(tmp_path)), '--dry-run')
    assert proc.returncode == 2


REPO = Path(__file__).resolve().parents[2]


def run_cli(tmp_path, *args, stdin=None, global_args=()):
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    env = {'PATH': os.environ['PATH'], 'HOME': str(home),
           'HERMES_HOME': str(home / 'profile'), 'HERMES_RUNTIME_DIR': str(home / 'runtime'),
           'PYTHONPATH': str(REPO)}
    # A dry-run must not even attempt a connection (including tokenizer downloads).
    bootstrap = ('import socket,runpy; '
                 'socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("network forbidden")); '
                 'runpy.run_module("hermes_cli.main",run_name="__main__")')
    return subprocess.run([sys.executable, '-c', bootstrap, *global_args, 'skills', 'select', *args],
                          cwd=REPO, env=env, text=True, input=stdin, capture_output=True, timeout=30)


def fixture_skills(tmp_path):
    root = tmp_path / 'skills'
    path = root / 'sample' / 'SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nname: sample\ndescription: Useful guidance.\n---\nPRIVATE BODY\n', encoding='utf-8')
    return root


def test_dry_run_prompt_short_flag_and_stdin(tmp_path):
    root = fixture_skills(tmp_path)
    for task in [('review',), ('-p', 'review'), ('--prompt', 'review'), ('-',)]:
        proc = run_cli(tmp_path, *task, '--skills-dir', str(root), '--dry-run', stdin='review')
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data['dry_run'] is True
        assert data['payloads'][0]['state']['task'] == 'review'
        assert 'PRIVATE BODY' not in proc.stdout
        assert str(root) not in json.dumps(data['payloads'])
        assert 'score' not in data


@pytest.mark.parametrize('document,reason', [
    ('---\nname: [PRIVATE INVALID YAML\n---\nPRIVATE BODY', 'invalid_yaml'),
    ('PRIVATE BODY', 'missing_frontmatter'),
    ('---\n- PRIVATE\n---', 'invalid_metadata'),
    ('---\nname: x\n---', 'missing_description'),
])
def test_skip_invalid_is_explicit_and_reports_safe_reason(tmp_path, document, reason):
    root = fixture_skills(tmp_path)
    invalid = root / 'broken' / 'SKILL.md'
    invalid.parent.mkdir()
    invalid.write_text(document, encoding='utf-8')
    args = ['review', '--skills-dir', str(root), '--dry-run']
    strict = run_cli(tmp_path, *args)
    assert strict.returncode == 2
    proc = run_cli(tmp_path, *args, '--skip-invalid')
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data['candidate_count'] == 1
    assert data['skipped'] == [{'path': 'broken/SKILL.md', 'reason': reason}]
    assert 'PRIVATE' not in proc.stdout + proc.stderr


def test_context_output_reports_invalid_omissions_on_stderr(tmp_path, monkeypatch, capsys):
    from hermes_cli.skills_select_cli import main
    from hermes_cli import skills_select_provider as provider
    root = fixture_skills(tmp_path)
    broken = root / 'broken' / 'SKILL.md'
    broken.parent.mkdir()
    broken.write_text('---\nname: [PRIVATE YAML\n---', encoding='utf-8')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'synthetic-key')
    monkeypatch.setattr(provider, 'score_payloads', lambda payloads, key: (
        {k: {'score': 8, 'confidence': .9} for p in payloads for k in p['questions']}, {}))
    assert main(['review', '--skills-dir', str(root), '--allow-upload', '--skip-invalid',
                 '--format', 'context']) == 0
    captured = capsys.readouterr()
    assert '<skill' in captured.out
    assert 'broken/SKILL.md' not in captured.out
    assert 'broken/SKILL.md' in captured.err and 'invalid_yaml' in captured.err
    assert 'PRIVATE YAML' not in captured.err


def test_upload_requires_explicit_consent(tmp_path):
    proc = run_cli(tmp_path, 'review', '--skills-dir', str(fixture_skills(tmp_path)))
    assert proc.returncode != 0
    assert '--allow-upload' in proc.stderr
