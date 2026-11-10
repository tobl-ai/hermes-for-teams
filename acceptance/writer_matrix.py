"""Additional writer release gates: actual registered backends, never xfail.

The local pipe lane passing does not waive PTY/persistent-kernel completion.
No model/provider/network or external resource mutations in these probes.
"""
import json
import shlex
import time
import threading

import pytest
pytest.importorskip('gateway.task_resources')
from backend_completion import private_backend


@pytest.mark.parametrize('cancel', [False, True])
def test_real_pty_completion_allows_following_native_writer(tmp_path, monkeypatch, cancel):
    model, _ = private_backend(tmp_path, monkeypatch)
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_CWD', str(tmp_path))
    path = tmp_path / 'pty-output'
    command = 'printf x > ' + shlex.quote(str(path)) + ('; sleep 30' if cancel else '')
    first = json.loads(model.handle_function_call('terminal', {'command': command,
        'workdir': str(tmp_path), 'background': True, 'pty': True}, task_id='matrix', skip_tool_execution_middleware=True))
    assert not first.get('error'), first
    sid = first['session_id']
    from tools.process_registry import process_registry
    try:
        if cancel:
            killed = json.loads(model.handle_function_call('process_manage', {'action': 'kill', 'session_id': sid},
                task_id='matrix', skip_tool_execution_middleware=True))
            assert not killed.get('error'), killed
        deadline = time.monotonic() + 8
        while not process_registry.get(sid).exited:
            assert time.monotonic() < deadline
            threading.Event().wait(.01)
        if not cancel:
            assert path.read_text() == 'x'
        second = json.loads(model.handle_function_call('write_file',
            {'path': str(tmp_path / 'after-pty'), 'content': 'next'}, task_id='matrix', skip_tool_execution_middleware=True))
        assert not second.get('error'), second
    finally:
        process_registry.kill_process(sid)


def test_real_persistent_kernel_completion_allows_following_native_writer(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    path = tmp_path / 'kernel-output'
    first = json.loads(model.handle_function_call('execute_code',
        {'code': f'from pathlib import Path\nPath({str(path)!r}).write_text("x")\nprint("kernel done")'},
        task_id='matrix-kernel', session_id='matrix-kernel', skip_tool_execution_middleware=True))
    assert not first.get('error'), first
    assert path.read_text() == 'x', first
    second = json.loads(model.handle_function_call('write_file',
        {'path': str(tmp_path / 'after-kernel'), 'content': 'next'}, task_id='matrix-kernel', skip_tool_execution_middleware=True))
    assert not second.get('error'), second
