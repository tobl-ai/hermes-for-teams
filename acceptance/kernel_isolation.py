"""Actual registered persistent cells: state retention and OS-enforced idle barrier."""
import json
import signal
import threading
import time

import pytest
pytest.importorskip('gateway.task_resources')
from backend_completion import private_backend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('TERMINAL_CWD', str(tmp_path))
    from tools.code_kernel import shutdown_all_kernels
    shutdown_all_kernels()
    def call(code):
        return json.loads(model.handle_function_call('execute_code', {'code': code},
            task_id='isolation', session_id='isolation', enabled_tools=['terminal','read_file','write_file','patch'],
            skip_tool_execution_middleware=True))
    yield model, call
    shutdown_all_kernels()


def test_consecutive_cells_keep_objects_then_native_write(backend, tmp_path):
    model, call = backend
    first = call('value = {"items": [1, 2]}\nprint("ready")')
    assert not first.get('error'), first
    second = call('value["items"].append(3)\nprint(value)')
    assert not second.get('error'), second
    assert "[1, 2, 3]" in second['output'] and second['kernel']['reused']
    assert second['kernel']['local_isolation'] == 'suspended'
    after = json.loads(model.handle_function_call('write_file',
        {'path': str(tmp_path / 'after'), 'content': 'native'}, skip_tool_execution_middleware=True))
    assert not after.get('error'), after
    assert (tmp_path / 'after').read_text() == 'native'


@pytest.mark.parametrize('kind', ['thread', 'subprocess', 'async', 'doublefork'])
def test_outliving_cell_is_frozen_and_resumes_only_with_next_lease(backend, tmp_path, kind):
    model, call = backend
    path = tmp_path / 'late'
    work = f'import time; time.sleep(.3); open({str(path)!r}, "w").write("late")'
    if kind == 'thread':
        code = f'import threading\ndef late():\n    exec({work!r})\nworker = threading.Thread(target=late); worker.start()'
    elif kind == 'subprocess':
        code = f'import subprocess, sys\nworker = subprocess.Popen([sys.executable, "-c", {work!r}], start_new_session=True)'
    elif kind == 'async':
        code = (f'import asyncio, threading\nasync def late():\n    await asyncio.sleep(.3)\n'
                f'    open({str(path)!r}, "w").write("late")\n'
                'worker = threading.Thread(target=lambda: asyncio.run(late())); worker.start()')
    else:
        daemon = f'import os; p=os.fork();\nif p == 0:\n os.setsid(); p=os.fork()\n if p == 0: exec({work!r})\n os._exit(0)\nos.waitpid(p,0)'
        code = f'import subprocess, sys\nworker = subprocess.Popen([sys.executable, "-c", {daemon!r}])'
    first = call(code)
    assert not first.get('error'), first
    assert first['kernel']['local_isolation'] == 'suspended', first
    threading.Event().wait(.5)
    assert not path.exists(), 'Detached writer ran while its lease was released'
    native = json.loads(model.handle_function_call('write_file',
        {'path': str(tmp_path / 'native'), 'content': 'other'}, skip_tool_execution_middleware=True))
    assert not native.get('error'), native
    second = call('import time; time.sleep(.6); print("resumed")')
    assert not second.get('error'), second
    assert path.read_text() == 'late'


@pytest.mark.parametrize('interrupted', [False, True])
def test_timeout_or_cancel_drains_exact_genealogy_and_restarts(backend, tmp_path, monkeypatch, interrupted):
    model, call = backend
    import tools.code_execution_tool as code_tool
    monkeypatch.setattr(code_tool, '_load_config', lambda: {'timeout': 1})
    if interrupted:
        import tools.interrupt
        started = time.monotonic()
        monkeypatch.setattr(tools.interrupt, 'is_interrupted', lambda: time.monotonic() - started > .4)
    path = tmp_path / 'late'
    child = f'import time; time.sleep(2); open({str(path)!r}, "w").write("bad")'
    result = call(f'import subprocess, sys, time\nworker=subprocess.Popen([sys.executable,"-c",{child!r}],start_new_session=True)\ntime.sleep(30)')
    assert result.get('error'), result
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path / 'resources.db').held_count() == 0
    threading.Event().wait(2)
    assert not path.exists()
    if interrupted:
        monkeypatch.setattr(tools.interrupt, 'is_interrupted', lambda: False)
    fresh = call('print("fresh")')
    assert not fresh.get('error') and not fresh['kernel']['reused'], fresh


def test_unexpected_kernel_death_retains_unknown_no_replay(backend, tmp_path):
    _, call = backend
    result = call('import os; os._exit(7)')
    assert result.get('error'), result
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path / 'resources.db').held_count() == 1
    again = call('print("must not replay")')
    assert again.get('error'), again


def test_late_thread_rpc_cannot_borrow_next_cell_authority(backend):
    _, call = backend
    first = call('import threading, time\nfrom hermes_tools import read_file\n'
                 'late_result = []\ndef late():\n    time.sleep(.3)\n'
                 '    late_result.append(read_file("/not-a-real-file"))\n'
                 'worker = threading.Thread(target=late); worker.start()')
    assert not first.get('error'), first
    second = call('time.sleep(.5)\nprint(late_result)')
    assert not second.get('error'), second
    assert 'No active execute_code cell' in second['output'], second
