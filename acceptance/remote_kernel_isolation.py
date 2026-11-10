"""Real remote file-RPC over a disposable shell transport (not a Docker claim).

No canned backend results: every execute launches a real shell/Python command.
A container CI lane can drive these same probes with its own backend transport.
"""
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest
pytest.importorskip('tools.remote_kernel_resource')
from backend_completion import private_backend
from remote_process_completion import RemoteShellEnvironment


class ShellTransport(RemoteShellEnvironment):
    def __init__(self, root):
        root.mkdir()
        super().__init__(root)


@pytest.fixture
def remote(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    transport = ShellTransport(tmp_path / 'remote-files')
    original_execute = transport.execute
    original_wait = transport._wait_for_process
    import tools.code_execution_tool as code_tool
    import tools.terminal_tool as terminal
    from tools.code_kernel_remote import shutdown_all_remote_kernels
    shutdown_all_remote_kernels()
    monkeypatch.setattr(terminal, '_get_env_config', lambda: {'env_type': 'fixture-posix', 'cwd': str(tmp_path), 'timeout': 10})
    monkeypatch.setattr(code_tool, '_get_or_create_env', lambda task_id: (transport, 'fixture-posix'))
    def call(code):
        return json.loads(model.handle_function_call('execute_code', {'code': code},
                         task_id='remote-physical', skip_tool_execution_middleware=True))
    yield model, call, transport
    monkeypatch.setattr(transport, 'execute', original_execute)
    monkeypatch.setattr(transport, '_wait_for_process', original_wait)
    shutdown_all_remote_kernels()


def test_remote_protocol_cells_keep_state_and_suspend_detached_writer(remote, tmp_path):
    model, call, _ = remote
    path = tmp_path / 'late'
    work = f'import time; time.sleep(2); open({str(path)!r},"w").write("late")'
    first = call(f'import sys, subprocess\nvalue = [1,2]\nworker=subprocess.Popen([sys.executable,"-c",{work!r}],start_new_session=True)\nprint("ready")')
    assert not first.get('error'), first
    threading.Event().wait(2.2)
    assert not path.exists(), 'Remote writer escaped idle suspension'
    after = json.loads(model.handle_function_call('write_file', {'path': str(tmp_path / 'after'), 'content': 'native'},
                       skip_tool_execution_middleware=True))
    assert not after.get('error'), after
    second = call('import time; time.sleep(.5); value.append(3); print(value)')
    assert not second.get('error') and '[1, 2, 3]' in second['output'], second
    assert path.read_text() == 'late'


def test_remote_missing_os_receipt_retains_lease_without_per_call_replay(remote, tmp_path, monkeypatch):
    _, call, transport = remote
    original = transport._wait_for_process
    started = tmp_path / 'started'
    def lose_receipt(proc, **kwargs):
        result = original(proc, **kwargs)
        if started.exists() and 'HERMES-OS-RECEIPT ' in result.get('output',''):
            result['output'] = '\n'.join(line for line in result['output'].splitlines() if not line.startswith('HERMES-OS-RECEIPT '))
        return result
    monkeypatch.setattr(transport, '_wait_for_process', lose_receipt)
    first = call(f'from pathlib import Path\np=Path({str(started)!r}); p.write_text(p.read_text()+"x" if p.exists() else "x")')
    assert first.get('error'), first
    assert started.read_text() == 'x', 'Uncertain request was replayed by per-call fallback'
    second = call('print("blocked")')
    assert second.get('error'), second


def test_remote_current_cell_effectful_rpc_and_old_thread_authority(remote,tmp_path):
    _,call,_=remote
    path=tmp_path/'remote-rpc'
    result=call(f'from hermes_tools import write_file,patch\nprint(write_file({str(path)!r},"one"))\n'
                f'print(patch(path={str(path)!r},old_string="one",new_string="two"))')
    assert not result.get('error') and not result.get('tool_errors'),result
    assert path.read_text()=='two'
    result=call('import threading,time\nfrom hermes_tools import read_file\nlate=[]\n'
                'def old():\n time.sleep(1)\n late.append(read_file("/not-real"))\n'
                'worker=threading.Thread(target=old);worker.start()')
    assert not result.get('error'),result
    after=call('worker.join(timeout=5)\nprint(late)')
    assert 'remote request authority retired' in after['output'],after
