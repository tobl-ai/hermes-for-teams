import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'compat.py'
BASE = '1fd18277267152893a8a24792b79213e7ca3f899'


def run(home, action='check', *extra):
    return subprocess.run([sys.executable, str(SCRIPT), action, '--hermes', str(home), *extra],
                          check=False, text=True, capture_output=True)


@pytest.fixture
def old_checkout(tmp_path):
    # Exact public commit, not reconstructed/fake fixture source. Sparse checkout
    # keeps this test small; the wrapper itself is exercised by legacy integration.
    import os
    if os.environ.get('HERMES_COMPAT_SOURCE'):
        source = Path(os.environ['HERMES_COMPAT_SOURCE']).resolve()
    else:
        gateway = pytest.importorskip('gateway')
        source = Path(gateway.__file__).resolve().parents[1]
    if subprocess.run(['git', '-C', str(source), 'cat-file', '-e', BASE], check=False, capture_output=True).returncode:
        pytest.skip('exact upstream commit not available; run native verifier with 1fd18277 checkout')
    home = tmp_path / 'hermes'
    subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(source), str(home)], check=True)
    subprocess.run(['git', '-C', str(home), 'sparse-checkout', 'set', '--no-cone',
                    '/gateway/run_turn.py', '/hermes_cli/middleware.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(home), 'checkout', '--quiet', '--detach', BASE], check=True)
    return home


def test_exact_old_commit_check_apply_and_idempotence(old_checkout, tmp_path):
    home = old_checkout
    assert not (home / 'gateway/session_finite.py').exists()
    untouched = home / 'local-settings.yaml'
    untouched.write_text('operator-setting: preserve\n')
    before = (home / 'gateway/run_turn.py').read_bytes()
    check = run(home)
    assert check.returncode == 0, check.stdout + check.stderr
    assert json.loads(check.stdout)['source_status'] == 'needs_patch'
    assert (home / 'gateway/run_turn.py').read_bytes() == before
    missing = run(home, 'apply')
    assert missing.returncode == 2
    assert (home / 'gateway/run_turn.py').read_bytes() == before
    applied = run(home, 'apply', '--backup-dir', str(tmp_path / 'private-backups'))
    assert applied.returncode == 0, applied.stdout + applied.stderr
    data = json.loads(applied.stdout)
    assert data['source_status'] == 'ready' and data['runtime_activated'] is False
    assert (Path(data['backup']) / 'gateway/run_turn.py').read_bytes() == before
    after = (home / 'gateway/run_turn.py').read_bytes()
    again = run(home, 'apply')
    assert again.returncode == 0
    assert (home / 'gateway/run_turn.py').read_bytes() == after
    assert untouched.read_text() == 'operator-setting: preserve\n'
    assert 'run_legacy_turn' in after.decode()


def test_conflicting_local_edit_fails_without_source_changes(old_checkout, tmp_path):
    home = old_checkout
    file = home / 'gateway/run_turn.py'
    original = file.read_text()
    assert 'self._profile_scope_for_source(source)' in original
    file.write_text(original.replace('self._profile_scope_for_source(source)', 'self.operator_custom_scope(source)'))
    before = file.read_bytes()
    result = run(home, 'apply', '--backup-dir', str(tmp_path / 'private'))
    assert result.returncode == 2
    assert file.read_bytes() == before
    assert not (home / 'gateway/turn_scheduling.py').exists()


def test_non_checkout_refused(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)['runtime_activated'] is False
