"""Physical synchronous write reservations; deliberately outside fail-open middleware."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
pytest.importorskip('gateway.task_resources')


@pytest.fixture(autouse=True)
def private_resource_authority(tmp_path, monkeypatch):
    from gateway import task_resources
    monkeypatch.setattr(task_resources, 'shared_guard_path', lambda: tmp_path / 'native-task-resources.sqlite3')


@pytest.mark.asyncio
async def test_native_write_lock_outlives_cancelled_async_waiter(tmp_path):
    import asyncio
    from gateway.task_resources import ResourceGuard
    guard = ResourceGuard(tmp_path / 'resources.db')
    path = tmp_path / 'artifact.txt'
    alias = tmp_path / 'alias.txt'
    alias.symlink_to(path)
    entered, release, second = threading.Event(), threading.Event(), threading.Event()
    def first(_args):
        entered.set()
        assert release.wait(8)
        path.write_text('first')
    def next_write(_args):
        second.set()
        path.write_text(path.read_text() + '+second')
    with ThreadPoolExecutor(max_workers=2) as pool:
        async def invoke():
            await asyncio.get_running_loop().run_in_executor(pool, lambda: guard.run('write_file', {'path': str(path)}, first))
        task = asyncio.create_task(invoke())
        await asyncio.to_thread(entered.wait, 8)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        future = pool.submit(lambda: guard.run('write_file', {'path': str(alias)}, next_write))
        try:
            # Inspect persistent reservation, not elapsed-time or thread scheduling guesses.
            assert guard.held_count() == 1
            assert not second.is_set()
        finally:
            release.set()
        future.result(8)
    assert path.read_text() == 'first+second'
    assert guard.held_count() == 0


def test_unknown_global_work_blocks_writes_across_guard_recreation(tmp_path):
    from gateway.task_resources import ResourceGuard, ResourceBusy
    path = tmp_path / 'resources.db'
    first = ResourceGuard(path)
    assert first.run('terminal', {'command': 'background operation', 'background': True}, lambda args: 'started') == 'started'
    replacement = ResourceGuard(path)
    with pytest.raises(ResourceBusy):
        replacement.run('write_file', {'path': str(tmp_path / 'a')}, lambda args: 'unsafe', wait=False)
    assert replacement.held_count() == 1


def test_actual_dispatch_reserves_even_when_execution_middleware_skipped(tmp_path, monkeypatch):
    import sqlite3
    from model_tools import handle_function_call
    import model_tools
    from gateway.task_resources import ResourceGuard
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    with sqlite3.connect(tmp_path / 'native-tasks.sqlite3') as db:
        db.execute('CREATE TABLE tasks (session TEXT, id TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)', ('branch-session', 'native-task'))
    observed = []
    guard = ResourceGuard(tmp_path / 'native-task-resources.sqlite3')
    def execute(*args, **kwargs):
        observed.append(guard.held_count())
        return '{"success":true}'
    monkeypatch.setattr(model_tools.registry, 'dispatch', execute)
    monkeypatch.setattr(model_tools, '_pre_dispatch_guards', lambda name, args, *rest: (args, None))
    handle_function_call('write_file', {'path': str(tmp_path / 'artifact'), 'content': 'x'},
                         session_id='branch-session', skip_tool_execution_middleware=True)
    assert observed == [1]
    assert guard.held_count() == 1  # no backend physical-done certificate


def test_actual_file_dispatch_cannot_claim_physical_completion_from_return(tmp_path, monkeypatch):
    import sqlite3
    import model_tools
    from gateway.task_resources import ResourceGuard
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    with sqlite3.connect(tmp_path / 'native-tasks.sqlite3') as db:
        db.execute('CREATE TABLE tasks (session TEXT, id TEXT)')
        db.execute('INSERT INTO tasks VALUES (?,?)', ('branch-session', 'native-task'))
    guard = ResourceGuard(tmp_path / 'native-task-resources.sqlite3')
    monkeypatch.setattr(model_tools.registry, 'dispatch', lambda *args, **kwargs: '{"error":"remote completion unknown"}')
    monkeypatch.setattr(model_tools, '_pre_dispatch_guards', lambda name, args, *rest: (args, None))
    model_tools.handle_function_call('write_file', {'path': str(tmp_path / 'artifact'), 'content': 'x'},
                         session_id='branch-session', skip_tool_execution_middleware=True)
    assert guard.held_count() == 1


def test_disjoint_known_file_writes_can_overlap(tmp_path):
    from gateway.task_resources import ResourceGuard
    guard = ResourceGuard(tmp_path / 'resources.db')
    barrier = threading.Barrier(2)
    def write(args):
        barrier.wait(8)
        return args['path']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(guard.run, 'write_file', {'path': str(tmp_path / name)}, write) for name in ('a', 'b')]
        assert {f.result(10) for f in futures} == {str(tmp_path / 'a'), str(tmp_path / 'b')}
