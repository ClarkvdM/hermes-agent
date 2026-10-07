"""Selection must stay on its env-only startup path across global flags."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[2]


def invoke(tmp_path, argv):
    profile = tmp_path / 'home' / 'profiles' / 'demo'
    skill = profile / 'skills' / 'sample' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: sample\ndescription: Synthetic guidance\n---\nbody', encoding='utf-8')
    (profile / 'config.yaml').write_text('{}\n', encoding='utf-8')
    bootstrap = '''
import runpy, sys, types
module = types.ModuleType('hermes_cli.env_loader')
def forbidden(*args, **kwargs):
    raise SystemExit(91)
module.load_hermes_dotenv = forbidden
sys.modules['hermes_cli.env_loader'] = module
runpy.run_module('hermes_cli.main', run_name='__main__')
'''
    env = {'PATH': os.environ['PATH'], 'HOME': str(tmp_path),
           'HERMES_HOME': str(tmp_path / 'home'),
           'HERMES_RUNTIME_DIR': str(tmp_path / 'runtime'), 'PYTHONPATH': str(REPO)}
    return subprocess.run([sys.executable, '-c', bootstrap, *argv],
                          cwd=REPO, env=env, text=True, capture_output=True, timeout=30)


@pytest.mark.parametrize('flags', [
    [], ['--yolo'], ['--ignore-rules'], ['--yolo', '--ignore-rules'],
    ['--model', 'skills'], ['--resume', 'select'],
])
@pytest.mark.parametrize('profile', [['--profile', 'demo'], ['-p', 'demo'], ['--profile=demo']])
def test_global_flags_keep_selection_offline_and_profile_scoped(tmp_path, flags, profile):
    proc = invoke(tmp_path, [*flags, *profile, 'skills', 'select', '-p', 'review', '--dry-run'])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result['dry_run'] is True
    assert result['candidate_count'] == 1
    assert result['payloads'][0]['state']['task'] == 'review'


@pytest.mark.parametrize('argv', [
    ['--yolo', 'skills', 'list'],
    ['--model', 'skills', 'select'],
    ['chat', 'skills', 'select'],
    ['--resume', 'skills', 'select'],
])
def test_selection_words_outside_command_boundary_keep_normal_startup(tmp_path, argv):
    # The intercepted loader proves these still take ordinary startup, without
    # actually reading dotenv or launching another command.
    assert invoke(tmp_path, argv).returncode == 91
