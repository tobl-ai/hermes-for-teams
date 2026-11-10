"""Registered native local terminal receipts, not registry return certificates."""
import json
import shlex
import sys
import threading
import time

import pytest
pytest.importorskip('gateway.task_resources')
from backend_completion import private_backend


def call(model, name, args, task='work'):
    return json.loads(model.handle_function_call(name, args, task_id=task,
                                               skip_tool_execution_middleware=True))


def until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'physical completion deadline'
        threading.Event().wait(.01)


def test_detached_native_writer_keeps_global_lease_until_physical_receipt(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_CWD', str(tmp_path))
    ready, release, output = [tmp_path / s for s in ('ready', 'release', 'output')]
    code = ('import os,time,pathlib; '
            'os.fork() and os._exit(0); os.setsid(); '
            'os.fork() and os._exit(0); '
            f'pathlib.Path({str(ready)!r}).touch(); '
            f'\nwhile not pathlib.Path({str(release)!r}).exists(): time.sleep(.01)\n'
            f'pathlib.Path({str(output)!r}).write_text("done")')
    result = call(model, 'terminal', {'command': shlex.join([sys.executable, '-c', code]),
                                    'workdir': str(tmp_path), 'timeout': 10})
    try:
        assert result.get('exit_code') == 0, result
        until(ready.exists)
        blocked = call(model, 'write_file', {'path': str(tmp_path / 'next'), 'content': 'next'})
        assert 'reservation' in blocked.get('error', ''), blocked
        release.touch()
        from gateway.task_resources import ResourceGuard
        until(lambda: ResourceGuard(tmp_path / 'resources.db').held_count() == 0)
        assert output.read_text() == 'done'
        assert not call(model, 'write_file', {'path': str(tmp_path / 'next'), 'content': 'next'}).get('error')
    finally:
        release.touch()


def test_timeout_reaps_local_descendants_and_settles_receipt(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_CWD', str(tmp_path))
    result = call(model, 'terminal', {'command': 'sleep 30', 'workdir': str(tmp_path), 'timeout': 1})
    assert result.get('exit_code') == 124, result
    from gateway.task_resources import ResourceGuard
    until(lambda: ResourceGuard(tmp_path / 'resources.db').held_count() == 0)
    assert not call(model, 'write_file', {'path': str(tmp_path / 'next'), 'content': 'next'}).get('error')


def test_background_lease_allows_own_poll_kill_but_not_stdin_or_other_owner(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_CWD', str(tmp_path))
    result = call(model, 'terminal', {'command': 'sleep 30', 'workdir': str(tmp_path), 'background': True})
    sid = result['session_id']
    try:
        blocked = call(model, 'process_manage', {'action': 'poll', 'session_id': sid}, task='other')
        assert 'reservation' in blocked.get('error', ''), blocked
        blocked = call(model, 'process_manage', {'action': 'write', 'session_id': sid, 'data': 'bad'})
        assert 'reservation' in blocked.get('error', ''), blocked
        polled = call(model, 'process_manage', {'action': 'poll', 'session_id': sid})
        assert not polled.get('error'), polled
        killed = call(model, 'process_manage', {'action': 'kill', 'session_id': sid})
        assert not killed.get('error'), killed
        from gateway.task_resources import ResourceGuard
        until(lambda: ResourceGuard(tmp_path / 'resources.db').held_count() == 0)
        assert not call(model, 'write_file', {'path': str(tmp_path / 'next'), 'content': 'next'}).get('error')
    finally:
        from tools.process_registry import process_registry
        process_registry.kill_process(sid)
