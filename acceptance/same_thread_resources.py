"""Release-blocking resource acceptance probes; NOT green unit fixtures.

Run explicitly via scripts/verify_automatic.py. These intentionally assert the
required product behavior, rather than asserting the WIP's permanent lockout.
No external tool, provider, file writer or credentials are invoked by dispatch.
"""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture(autouse=True)
def private_resource_authority(tmp_path, monkeypatch):
    from gateway import task_resources
    monkeypatch.setattr(task_resources, 'shared_guard_path', lambda: tmp_path / 'native-task-resources.sqlite3')

pytest.importorskip('gateway.run')


def prepare(tmp_path, monkeypatch):
    import model_tools
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    with sqlite3.connect(tmp_path / 'native-tasks.sqlite3') as db:
        db.execute('CREATE TABLE tasks (session TEXT, id TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)', ('branch-session', 'native-task'))
    monkeypatch.setattr(model_tools, '_pre_dispatch_guards', lambda name, args, *rest: (args, None))
    return model_tools


def test_completed_local_write_allows_next_disjoint_write(tmp_path, monkeypatch):
    model = prepare(tmp_path, monkeypatch)
    # Exercise the real registered file backend: a synthetic JSON success is
    # deliberately NOT a physical-completion certificate.
    from tools.file_operations import ShellFileOperations
    from tools.environments.local import LocalEnvironment
    import tools.file_tools as files
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)))
    monkeypatch.setattr(files, '_get_file_ops', lambda task_id='default': ops)
    for filename in ('a', 'b'):
        result = model.handle_function_call('write_file', {'path': str(tmp_path / filename), 'content': 'x'},
                                  session_id='branch-session', skip_tool_execution_middleware=True)
        import json
        assert not json.loads(result).get('error'), result
        assert (tmp_path / filename).read_text() == 'x', result


def test_nonbranch_writer_cannot_bypass_live_branch_reservation(tmp_path, monkeypatch):
    model = prepare(tmp_path, monkeypatch)

    entered, release = threading.Event(), threading.Event()
    escaped = []
    def dispatch(name, args, **kwargs):
        if args['content'] == 'branch':
            entered.set()
            assert release.wait(8)
        else:
            escaped.append(args['content'])
        return '{"success": true}'
    monkeypatch.setattr(model.registry, 'dispatch', dispatch)
    path = str(tmp_path / 'shared')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(model.handle_function_call, 'write_file', {'path': path, 'content': 'branch'},
                             session_id='branch-session', skip_tool_execution_middleware=True)
        try:
            assert entered.wait(8)
            result = model.handle_function_call('write_file', {'path': path, 'content': 'unbranched'},
                                               session_id='ordinary-session', skip_tool_execution_middleware=True)
            assert not escaped
            assert 'reservation' in result
        finally:
            release.set()
            future.result(8)
