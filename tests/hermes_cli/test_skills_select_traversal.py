"""Traversal failures must never silently certify a partial skill inventory."""
import errno
import json
import os
from pathlib import Path

import pytest

from hermes_cli.skills_select import discover_skills
from hermes_cli.skills_select_cli import main


@pytest.fixture
def unreadable_inventory(tmp_path, monkeypatch):
    root = tmp_path / 'skills'
    for name in ['readable', 'nested/blocked']:
        path = root / name / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(f'---\nname: {name}\ndescription: Synthetic guidance\n---\nbody', encoding='utf-8')
    scandir = os.scandir

    def fail_directory(path):
        if Path(path) == root / 'nested' / 'blocked':
            raise PermissionError(errno.EACCES, 'SYNTHETIC_SECRET', str(path))
        return scandir(path)

    # Inject at the OS seam, not os.walk: exercise its actual onerror handling
    # even on hosts where permissions cannot make a directory unreadable.
    monkeypatch.setattr(os, 'scandir', fail_directory)
    return root


def test_strict_discovery_raises_safe_traversal_error(unreadable_inventory, capsys):
    with pytest.raises(OSError) as error:
        discover_skills(unreadable_inventory)
    assert str(Path('nested') / 'blocked') in str(error.value)
    assert 'SYNTHETIC_SECRET' not in str(error.value)
    assert str(unreadable_inventory) not in str(error.value)
    assert main(['review', '--skills-dir', str(unreadable_inventory), '--dry-run']) == 2
    output = capsys.readouterr()
    assert output.out == ''
    assert str(Path('nested') / 'blocked') in output.err
    assert 'SYNTHETIC_SECRET' not in output.err


@pytest.mark.parametrize('format', ['json', 'context'])
def test_skip_invalid_reports_safe_traversal_omission(unreadable_inventory, monkeypatch, capsys, format):
    from hermes_cli import skills_select_provider as provider

    monkeypatch.setenv('TYPESAFE_API_KEY', 'synthetic-key')
    monkeypatch.setattr(provider, 'score_payloads', lambda payloads, key: (
        {k: {'score': 8, 'confidence': .9} for p in payloads for k in p['questions']}, {}))
    args = ['review', '--skills-dir', str(unreadable_inventory), '--skip-invalid']
    args += ['--dry-run'] if format == 'json' else ['--allow-upload', '--format', 'context']
    assert main(args) == 0
    output = capsys.readouterr()
    omission = {'path': str(Path('nested') / 'blocked'), 'reason': 'traversal_error'}
    if format == 'json':
        result = json.loads(output.out)
        assert result['candidate_count'] == 1
        assert result['skipped'] == [omission]
    else:
        assert '<skill' in output.out
        assert 'nested/blocked' not in output.out
        assert json.loads(output.err.split('omitted ', 1)[1]) == omission
    assert 'SYNTHETIC_SECRET' not in output.out + output.err
    assert str(unreadable_inventory) not in output.out + output.err
