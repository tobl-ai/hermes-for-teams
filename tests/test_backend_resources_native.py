"""Real backend lease integration, separate from prototype ResourceGuard tests."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
pytest.importorskip('gateway.task_resources')


def test_other_profile_writer_participates_without_own_task_ledger(tmp_path, monkeypatch):
    from gateway import task_resources as resources
    home_a, home_b = tmp_path / 'a', tmp_path / 'b'
    home_a.mkdir()
    home_b.mkdir()
    with sqlite3.connect(home_a / 'native-tasks.sqlite3'):
        pass
    # Host lease authority is shared across profiles, never profile-local.
    monkeypatch.setattr(resources, 'shared_guard_path', lambda: tmp_path / 'shared.db', raising=False)
    monkeypatch.setenv('HERMES_HOME', str(home_a))
    entered, release = threading.Event(), threading.Event()
    escaped = []
    ids = SimpleNamespace(task_id='task')
    def run(_):
        entered.set()
        assert release.wait(8)
        return 'unknown backend result'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(resources.dispatch_reserved, 'terminal', {}, ids, run)
        try:
            assert entered.wait(8)
            monkeypatch.setenv('HERMES_HOME', str(home_b))
            with pytest.raises(resources.ResourceBusy):
                resources.dispatch_reserved('terminal', {}, ids, lambda _: escaped.append('b'))
            assert not escaped
        finally:
            release.set()
            future.result(8)

def test_witness_refuses_changed_handler_arguments_before_io(tmp_path, monkeypatch):
    from gateway import task_resources as resources
    from tools.file_operations import ShellFileOperations
    from tools.environments.local import LocalEnvironment
    import tools.file_tools as files
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setattr(resources, 'shared_guard_path', lambda: tmp_path / 'shared.db')
    with sqlite3.connect(tmp_path / 'native-tasks.sqlite3'):
        pass
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)))
    monkeypatch.setattr(files, '_get_file_ops', lambda task_id='default': ops)
    args = {'path': str(tmp_path / 'reserved'), 'content': 'x'}
    def changed(_):
        return files._handle_write_file({'path': str(tmp_path / 'different'), 'content': 'x'}, task_id='task')
    try:
        result = resources.dispatch_reserved('write_file', args, SimpleNamespace(task_id='task'), changed)
    except resources.ResourceBusy:
        pass
    assert not (tmp_path / 'different').exists()


def test_narrow_witness_blocks_managed_linter_before_spawn(tmp_path, monkeypatch):
    from tools.file_resource_contract import FileCompletion, _current
    from gateway.task_resources import ResourceBusy
    from tools.file_operations import ShellFileOperations
    from tools.environments.local import LocalEnvironment
    import subprocess
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)))
    spawned = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: spawned.append(a))
    token = _current.set(FileCompletion('write_file', ('path:' + str(tmp_path / 'a.ts'),)))
    try:
        with pytest.raises(ResourceBusy):
            ops._run_managed_node_linter('.ts', str(tmp_path / 'a.ts'))
        assert not spawned
    finally:
        _current.reset(token)


def test_narrow_witness_queues_lsp_without_starting_it_inline(tmp_path, monkeypatch):
    from tools.file_resource_contract import FileCompletion, _current
    from gateway.task_resources import ResourceBusy
    from tools.file_operations import ShellFileOperations
    from tools.environments.local import LocalEnvironment
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)))
    monkeypatch.setattr(ops, '_lsp_service', lambda: object())
    monkeypatch.setattr(ops, '_lsp_will_handle', lambda path: True)
    plans = []
    def queue(ops, path, pre, post):
        plans.append(path)
        return 'Native diagnostics pending'
    monkeypatch.setattr('tools.native_diagnostics.queue_diagnostics', queue)
    token = _current.set(FileCompletion('write_file', ('path:' + str(tmp_path / 'a.ts'),)))
    try:
        assert 'pending' in ops._maybe_lsp_diagnostics(str(tmp_path / 'a.ts'))
        assert plans == [str(tmp_path / 'a.ts')]
    finally:
        _current.reset(token)
