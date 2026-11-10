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
def old_checkout(tmp_path, request):
    # Exact public commit, not reconstructed/fake fixture source. Sparse checkout
    # keeps this test small; the wrapper itself is exercised by legacy integration.
    import os
    if os.environ.get('HERMES_COMPAT_SOURCE'):
        source = Path(os.environ['HERMES_COMPAT_SOURCE']).resolve()
    else:
        gateway = pytest.importorskip('gateway')
        source = Path(gateway.__file__).resolve().parents[1]
    base = getattr(request, 'param', BASE)
    if subprocess.run(['git', '-C', str(source), 'cat-file', '-e', base], check=False, capture_output=True).returncode:
        pytest.skip('exact upstream commit not available; run native verifier with 1fd18277 checkout')
    home = tmp_path / 'hermes'
    # Fetch only the required trees. Cloning all advertised refs from a partial
    # source can traverse unrelated missing promisor objects, even with --shared.
    # Keep the submission baseline for the real compatibility selector, not a
    # new revision allowlist, and retain shallow multi-ref CI coverage.
    subprocess.run(['git', 'init', '--quiet', str(home)], check=True)
    subprocess.run(['git', '-C', str(home), 'remote', 'add', 'origin', str(source)], check=True)
    refs = [base]
    if base in ('b200f5bc60e31588ba2cb60e288029c4a54ba5fa',
                'ed1afb082eb3e46cf2edae9d8f68fb67b09ee4df'):
        refs.append('f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab')
    result = subprocess.run(['git', '-C', str(home), 'fetch', '--quiet', '--depth', '1',
                             'origin', *refs], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    if base not in ('b200f5bc60e31588ba2cb60e288029c4a54ba5fa','aab7134651366febd15d00553301c10607d1cbf4'):
        subprocess.run(['git', '-C', str(home), 'sparse-checkout', 'set', '--no-cone',
                        '/gateway/run_turn.py', '/gateway/session_finite.py',
                        '/gateway/session_runtime_workers.py', '/hermes_cli/middleware.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(home), 'checkout', '--quiet', '--detach', base], check=True)
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


def commit_change(home, path, content):
    target = home / path
    target.write_text(content)
    subprocess.run(['git', '-C', str(home), 'add', '--sparse', '--', path], check=True)
    subprocess.run(['git', '-C', str(home), '-c', 'user.name=Compatibility Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture change'], check=True)


def test_unrelated_new_revision_accepts_same_execution_layout(old_checkout, tmp_path):
    commit_change(old_checkout, 'release-note.txt', 'unrelated upstream update\n')
    result = run(old_checkout)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)['source_status'] == 'needs_patch'
    applied = run(old_checkout, 'apply', '--backup-dir', str(tmp_path / 'backups'))
    assert applied.returncode == 0, applied.stdout
    assert run(old_checkout).returncode == 0


def test_changed_execution_layout_refused_even_when_patch_could_apply(old_checkout):
    path = 'gateway/run_turn.py'
    content = (old_checkout / path).read_text()
    commit_change(old_checkout, path, content + '\n# execution module changed upstream\n')
    before = (old_checkout / path).read_bytes()
    result = run(old_checkout)
    assert result.returncode == 2
    assert 'Unsupported Hermes execution layout' in result.stdout
    assert (old_checkout / path).read_bytes() == before


@pytest.mark.parametrize('old_checkout', [
    'bf0203a794a07aac3ff764972ab9087baa4e4f4e',
    'f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab',
    'b200f5bc60e31588ba2cb60e288029c4a54ba5fa',
    'aab7134651366febd15d00553301c10607d1cbf4',
    'ed1afb082eb3e46cf2edae9d8f68fb67b09ee4df'], indirect=True)
def test_current_submission_layout_apply_and_idempotence(old_checkout, tmp_path):
    home = old_checkout
    target = home / 'gateway/session_finite.py'
    before = target.read_bytes()
    check = run(home)
    assert check.returncode == 0, check.stdout + check.stderr
    assert json.loads(check.stdout)['source_status'] == 'needs_patch'
    assert target.read_bytes() == before
    applied = run(home, 'apply', '--backup-dir', str(tmp_path / 'backups'))
    assert applied.returncode == 0, applied.stdout + applied.stderr
    data = json.loads(applied.stdout)
    assert data['source_status'] == 'ready' and data['runtime_activated'] is False
    assert (Path(data['backup']) / 'gateway/session_finite.py').read_bytes() == before
    after = target.read_bytes()
    scope = b"submission_turn_scope(row['admission_id'], row.get('request_id'))"
    assert (scope in after) == (scope in before)
    assert b'run_scheduled_turn' in after
    assert run(home, 'apply').returncode == 0
    assert target.read_bytes() == after


def test_line_ending_only_blob_change_is_not_identical(old_checkout):
    path = 'gateway/run_turn.py'
    target = old_checkout / path
    original = target.read_bytes()
    (old_checkout / '.git/info/attributes').write_text(path + ' -text\n')
    target.write_bytes(original.replace(b'\n', b'\r\n'))
    subprocess.run(['git', '-C', str(old_checkout), 'add', '--sparse', '--', path], check=True)
    subprocess.run(['git', '-C', str(old_checkout), '-c', 'user.name=Compatibility Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture newline'], check=True)
    result = run(old_checkout)
    assert result.returncode == 2
    assert 'Unsupported Hermes execution layout' in result.stdout


def test_non_checkout_refused(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)['runtime_activated'] is False
