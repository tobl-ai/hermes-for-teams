"""Unfinished physical backend gates. Explicit RED release probes, never xfail."""
import json
import shlex
import sqlite3
import pytest

pytest.importorskip('gateway.task_resources')


def private_backend(tmp_path, monkeypatch):
    from gateway import task_resources
    import model_tools
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setattr(task_resources, 'shared_guard_path', lambda: tmp_path / 'resources.db')
    with sqlite3.connect(tmp_path / 'native-tasks.sqlite3'):
        pass
    from tools.file_operations import ShellFileOperations
    from tools.environments.local import LocalEnvironment
    import tools.file_tools as files
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)))
    monkeypatch.setattr(files, '_get_file_ops', lambda task_id='default': ops)
    return model_tools, ops


def test_native_js_write_never_reports_generic_failure_after_mutation(tmp_path, monkeypatch):
    model, ops = private_backend(tmp_path, monkeypatch)
    monkeypatch.setattr(ops, '_lsp_local_only', lambda: True)
    path = tmp_path / 'probe.js'
    result = json.loads(model.handle_function_call('write_file', {'path': str(path), 'content': 'const a = 1;'},
                                                skip_tool_execution_middleware=True))
    assert not (result.get('error') and path.exists()), result
    assert path.exists() and not result.get('error'), result


def test_real_local_terminal_completion_allows_next_write(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    # Explicit local backend and private cwd only. No network, credentials or daemon.
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_CWD', str(tmp_path))
    path = tmp_path / 'shell-output'
    first = json.loads(model.handle_function_call('terminal',
        {'command': 'printf x > ' + shlex.quote(str(path)), 'workdir': str(tmp_path), 'timeout': 10},
        skip_tool_execution_middleware=True))
    assert not first.get('error') and path.read_text() == 'x', first
    second = json.loads(model.handle_function_call('write_file',
        {'path': str(tmp_path / 'next'), 'content': 'next'}, skip_tool_execution_middleware=True))
    assert not second.get('error'), second
