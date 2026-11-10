"""Native remote supervisor over actual BaseEnvironment execution, no canned I/O.

A shell-backed transport exercises the remote protocol locally; this is distinct
from exercising the Docker daemon, SSH, or a vendor sandbox runtime.
"""
import json
import os
import signal
import sqlite3
import subprocess
import threading

import pytest
pytest.importorskip('tools.environments.remote_supervision')
from tools.environments.base import BaseEnvironment


class RemoteShellEnvironment(BaseEnvironment):
    uses_host_filesystem = False
    def __init__(self, root):
        self.root = root
        super().__init__(cwd=str(root), timeout=10, persist_env=False)
        self._snapshot_ready = False
        self._prefer_nonlogin = True
    def get_temp_dir(self):
        return str(self.root)
    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None):
        return self._run_native_argv(['bash', '-c', cmd_string], timeout=timeout, stdin_data=stdin_data)
    def _run_native_argv(self, argv, *, timeout=120, stdin_data=None):
        proc = subprocess.Popen(argv, cwd=str(self.root),
                                env=os.environ.copy(), start_new_session=True, text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        def feed():
            try:
                if stdin_data is not None:
                    proc.stdin.write(stdin_data)
                proc.stdin.close()
            except BrokenPipeError:
                pass
        proc._hermes_stdin_thread = threading.Thread(target=feed, daemon=True)
        proc._hermes_stdin_thread.start()
        return proc
    def _kill_process(self, proc):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    def cleanup(self):
        pass


def test_remote_shell_native_file_writes_settle_all_physical_operations(tmp_path, monkeypatch):
    from backend_completion import private_backend
    model, _ = private_backend(tmp_path, monkeypatch)
    from tools.file_operations import ShellFileOperations
    import tools.file_tools as files
    ops = ShellFileOperations(RemoteShellEnvironment(tmp_path))
    monkeypatch.setattr(files, '_get_file_ops', lambda task_id='default': ops)
    for name in ['first', 'second']:
        result = json.loads(model.handle_function_call('write_file', {'path': str(tmp_path / name), 'content': 'remote'},
                                                   skip_tool_execution_middleware=True))
        assert not result.get('error'), result
        assert (tmp_path / name).read_text() == 'remote'
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path / 'resources.db').held_count() == 0
    with sqlite3.connect(tmp_path / 'resources.db') as db:
        rows = db.execute('SELECT state FROM physical_operations').fetchall()
    assert rows and all(row[0] == 'physical_done' for row in rows)


def test_remote_shell_completion_drains_detached_descendant(tmp_path):
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import reserved_terminal
    env = RemoteShellEnvironment(tmp_path)
    guard = ResourceGuard(tmp_path / 'resources.db')
    path = tmp_path / 'late'
    script = f'import os,time; p=os.fork();\nif p == 0:\n os.setsid(); time.sleep(.3); open({str(path)!r},"w").write("done"); os._exit(0)\nos._exit(0)'
    import shlex
    command = 'python3 -c ' + shlex.quote(script)
    result = reserved_terminal(guard, {}, lambda _: env.execute(command))
    assert result['returncode'] == 0, result
    assert path.read_text() == 'done'
    assert guard.held_count() == 0


def test_arbitrary_success_cannot_settle_remote_operation(tmp_path):
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import reserved_terminal
    guard = ResourceGuard(tmp_path / 'resources.db')
    reserved_terminal(guard, {}, lambda _: {'physical_done': True, 'returncode': 0})
    assert guard.held_count() == 1


@pytest.mark.parametrize('cancel', [False, True])
def test_real_remote_background_completion_or_targeted_cancel(tmp_path, cancel):
    import time
    import shlex
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import reserved_terminal
    from tools.process_registry import process_registry
    guard = ResourceGuard(tmp_path / 'resources.db')
    env = RemoteShellEnvironment(tmp_path)
    path = tmp_path / 'late'
    command = 'sleep ' + ('30' if cancel else '.5') + '; printf done > ' + shlex.quote(str(path))
    session = reserved_terminal(guard, {}, lambda _: process_registry.spawn_via_env(
        env, command, cwd=str(tmp_path), task_id='remote-bg', owner_task_id='remote-bg'))
    try:
        receipt = session._native_remote_receipt
        deadline = time.monotonic() + 10
        while receipt.ready is None and not receipt.done:
            assert time.monotonic() < deadline
            threading.Event().wait(.025)
        if cancel:
            assert guard.held_count() == 1
            process_registry.kill_process(session.id)
        while guard.held_count():
            assert time.monotonic() < deadline
            threading.Event().wait(.025)
        if cancel:
            assert not path.exists()
        else:
            assert path.read_text() == 'done'
        while not session.exited:
            assert time.monotonic() < deadline
            threading.Event().wait(.025)
    finally:
        process_registry.kill_process(session.id)


def test_remote_outer_shell_startup_is_below_physical_supervisor(tmp_path, monkeypatch):
    import shlex
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import reserved_terminal
    path = tmp_path / 'startup-late'
    startup = tmp_path / 'bash-env'
    startup.write_text('trap ":" EXIT\nif [ -z "$STARTUP_REPRO" ]; then\nexport STARTUP_REPRO=1\n'
                       '(sleep .5; printf late > '+shlex.quote(str(path))+') >/dev/null 2>&1 &\nfi\n')
    monkeypatch.setenv('BASH_ENV',str(startup))
    guard=ResourceGuard(tmp_path/'startup-resources.db')
    result=reserved_terminal(guard,{},lambda _:RemoteShellEnvironment(tmp_path).execute('printf command'))
    assert result['returncode']==0 and path.exists(),result
    assert guard.held_count()==0
    guard.run('write_file',{'path':str(path)},lambda _:path.write_text('new-owner'))
    threading.Event().wait(.6)
    assert path.read_text()=='new-owner'
