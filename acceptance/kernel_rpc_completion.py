"""Active persistent-cell native RPC ownership and physical child aggregation."""
import json
import shlex
import sys
import threading
import time

import pytest
pytest.importorskip('tools.kernel_resource_contract')
from kernel_isolation import backend


def test_active_cell_native_write_and_patch_rpc(backend, tmp_path):
    _, call = backend
    path = tmp_path / 'rpc-write'
    first = call(f'from hermes_tools import write_file, patch\nprint(write_file({str(path)!r},"first"))\n'
                 f'print(patch(path={str(path)!r},old_string="first",new_string="second"))')
    assert not first.get('error') and not first.get('tool_errors'), first
    assert path.read_text() == 'second'
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path / 'resources.db').held_count() == 0


def test_outliving_active_rpc_is_aggregated_into_parent_lease(backend, tmp_path):
    model, call = backend
    gate = tmp_path / 'release-child'
    late = tmp_path / 'rpc-late'
    child = (f'import os,time; from pathlib import Path; p=os.fork();\n'
             f'if p == 0:\n os.setsid(); os.close(1); os.close(2)\n'
             f' while not Path({str(gate)!r}).exists(): time.sleep(.02)\n'
             f' Path({str(late)!r}).write_text("done"); os._exit(0)\n'
             'os._exit(0)')
    command = shlex.quote(sys.executable) + ' -c ' + shlex.quote(child)
    try:
        result = call(f'from hermes_tools import terminal\nprint(terminal({command!r},timeout=10))')
        assert not result.get('error') and not result.get('tool_errors'), result
        from gateway.task_resources import ResourceGuard
        guard = ResourceGuard(tmp_path / 'resources.db')
        assert guard.held_count() == 1 and not late.exists(), result
        blocked = json.loads(model.handle_function_call('write_file',
            {'path':str(tmp_path/'following'),'content':'must wait'},skip_tool_execution_middleware=True))
        assert blocked.get('error'), blocked
        gate.touch()
        deadline = time.monotonic() + 10
        while guard.held_count():
            assert time.monotonic() < deadline
            threading.Event().wait(.025)
        assert late.read_text() == 'done'
    finally:
        gate.touch()


def test_unwitnessed_rpc_handler_json_keeps_parent_unknown(backend, tmp_path, monkeypatch):
    model, call = backend
    original = model.registry.dispatch
    def dispatch(name, args, **kwargs):
        if name == 'terminal':
            return '{"exit_code":0,"physical_done":true}'
        return original(name,args,**kwargs)
    monkeypatch.setattr(model.registry,'dispatch',dispatch)
    result = call('from hermes_tools import terminal\nprint(terminal("printf ignored"))')
    assert not result.get('error'), result
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path/'resources.db').held_count() == 1
