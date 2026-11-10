"""Actual Linux genealogy, not process-registry JSON, certifies local completion."""
import os
from pathlib import Path
import shlex
import signal
import sys
import threading

import pytest

pytest.importorskip('gateway.task_resources')


def supervisor():
    from tools.environments.local_supervision import spawn_supervised
    return spawn_supervised


def test_immediate_cancel_drains_after_readiness_handshake(tmp_path):
    for _ in range(5):
        done = threading.Event()
        proc = supervisor()([sys.executable, '-c', 'import time; time.sleep(30)'],
            on_physical_done=done.set, cwd=str(tmp_path), stdout=-1, stderr=-2,
            stdin=-3, text=True, start_new_session=True)
        proc.kill()
        proc.wait(timeout=5)
        assert done.wait(5)


def test_double_fork_setsid_keeps_physical_work_after_root_exit(tmp_path):
    spawn = supervisor()
    done = threading.Event()
    ready, release, output = [tmp_path / p for p in ('ready', 'release', 'output')]
    child = ('import os,time,pathlib; '
             'os.fork() and os._exit(0); os.setsid(); '
             'os.fork() and os._exit(0); '
             f'pathlib.Path({str(ready)!r}).touch(); '
             f'\nwhile not pathlib.Path({str(release)!r}).exists(): time.sleep(.01)\n'
             f'pathlib.Path({str(output)!r}).write_text("done")')
    proc = spawn([sys.executable, '-c', child], on_physical_done=done.set,
                 cwd=str(tmp_path), env=os.environ.copy(), stdout=-1, stderr=-2,
                 stdin=-3, text=True, start_new_session=True)
    try:
        assert proc.wait(timeout=5) == 0
        from time import monotonic
        deadline = monotonic() + 5
        while not ready.exists() and monotonic() < deadline:
            threading.Event().wait(.01)
        assert ready.exists()
        assert not done.is_set()
        release.touch()
        assert done.wait(5)
        assert output.read_text() == 'done'
    finally:
        release.touch()
        proc.kill()


def test_supervisor_death_never_certifies_completion(tmp_path):
    spawn = supervisor()
    done = threading.Event()
    proc = spawn(['/bin/sh', '-c', 'exit 7'], on_physical_done=done.set,
                 cwd=str(tmp_path), env=os.environ.copy(), stdout=-1, stderr=-2,
                 stdin=-3, text=True, start_new_session=True)
    # Completion normally preserves the root's nonzero status.
    assert proc.wait(timeout=5) == 7
    assert done.wait(5)
    hold = tmp_path / 'hold'
    proc = spawn([sys.executable, '-c', 'import time; time.sleep(30)'],
                 on_physical_done=lambda: hold.touch(), cwd=str(tmp_path),
                 env=os.environ.copy(), stdout=-1, stderr=-2, stdin=-3,
                 text=True, start_new_session=True)
    # Kill the whole isolated test group to leave no test child behind.
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    assert not hold.exists()
