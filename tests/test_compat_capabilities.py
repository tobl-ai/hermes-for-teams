"""Capability selection uses native execution blobs, not version claims."""
import json
import pytest
from test_compat_cli import old_checkout,run,commit_change


@pytest.mark.parametrize('old_checkout',[
    'b200f5bc60e31588ba2cb60e288029c4a54ba5fa',
    'aab7134651366febd15d00553301c10607d1cbf4'],indirect=True)
def test_same_thread_capability_apply_readback_and_execution_drift(old_checkout,tmp_path,monkeypatch):
    # Packaged patches contain native Korean text; locale-default decoding must
    # not regress on Windows cp1252 or an explicitly non-UTF8 Python process.
    monkeypatch.setenv('PYTHONUTF8','0')
    monkeypatch.setenv('PYTHONCOERCECLOCALE','0')
    monkeypatch.setenv('LC_ALL','C')
    home=old_checkout
    check=run(home,'check','--capability','same-thread')
    assert check.returncode==0,check.stdout+check.stderr
    assert 'same-thread' in json.loads(check.stdout)['capabilities']
    commit_change(home,'unrelated-release.txt','unrelated revision\n')
    assert run(home,'check','--capability','same-thread').returncode==0
    applied=run(home,'apply','--capability','same-thread','--backup-dir',str(tmp_path/'backups'))
    assert applied.returncode==0,applied.stdout+applied.stderr
    assert (home/'tools/native_remote_kernel.py').exists()
    assert json.loads(run(home,'check','--capability','same-thread').stdout)['source_status']=='ready'
    assert run(home,'apply','--capability','same-thread').returncode==0
    path='tools/code_execution_tool.py'
    # Change the official HEAD blob in a second clean checkout state. A comment
    # still changes the reviewed execution contract and must not fuzzy-match.
    import subprocess
    subprocess.run(['git','-C',str(home),'reset','--hard','HEAD'],check=True,capture_output=True)
    commit_change(home,path,(home/path).read_text(encoding='utf-8')+'\n# execution drift\n')
    refused=run(home,'check','--capability','same-thread')
    assert refused.returncode==2,refused.stdout
    assert 'Unsupported Hermes execution layout' in refused.stdout


def test_legacy_cannot_claim_same_thread_capability(old_checkout):
    refused=run(old_checkout,'check','--capability','same-thread')
    assert refused.returncode==2,refused.stdout
    assert 'Unsupported Hermes execution layout' in refused.stdout
