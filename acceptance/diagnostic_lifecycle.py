"""Real disposable lint/LSP workers and native physical resource receipts."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
pytest.importorskip('tools.native_diagnostics')
from backend_completion import private_backend


def receipt(tmp_path):
    with sqlite3.connect(tmp_path / 'resources.db') as db:
        try:
            return db.execute('SELECT state,output FROM diagnostics ORDER BY rowid DESC LIMIT 1').fetchone()
        except sqlite3.OperationalError:
            return None


def wait_receipt(tmp_path):
    deadline = time.monotonic() + 30
    while True:
        row = receipt(tmp_path)
        if row and row[0] in {'completed', 'unknown'}:
            return row
        assert time.monotonic() < deadline, row
        threading.Event().wait(.025)


def test_registered_write_runs_real_external_diagnostic_worker(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    path = tmp_path / 'probe.js'
    result = json.loads(model.handle_function_call('write_file', {'path': str(path), 'content': 'const x = ;'},
                                                skip_tool_execution_middleware=True))
    assert not result.get('error') and path.exists(), result
    row = wait_receipt(tmp_path)
    assert row[0] == 'completed', row  # PM-managed Node may be absent in this disposable home.
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path / 'resources.db').held_count() == 0
    with sqlite3.connect(tmp_path / 'resources.db') as db:
        operations = db.execute('SELECT state FROM physical_operations').fetchall()
    assert operations and all(row[0] == 'physical_done' for row in operations)


def test_actual_node_syntax_process_has_physical_receipt(tmp_path):
    import shutil
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import ProcessCompletion
    node = shutil.which('node')
    assert node is not None, 'This acceptance lane requires a real Node executable'
    guard = ResourceGuard(tmp_path / 'node-resources.db')
    lease = guard.acquire(('*',))
    witness = ProcessCompletion(guard, lease)
    witness.local_handler = True
    proc = witness.spawn([node, '--check'], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output, _ = proc._supervisor.communicate(b'const broken = ;', timeout=10)
    witness.seal()
    assert proc._physical_done.wait(5)
    assert 'SyntaxError' in output.decode() and proc.returncode != 0
    assert guard.held_count() == 0


def test_real_config_declared_lsp_worker_returns_diagnostic_and_drains(tmp_path, monkeypatch):
    model, _ = private_backend(tmp_path, monkeypatch)
    import tools.code_kernel
    core = Path(tools.code_kernel.__file__).resolve().parents[1]
    mock = core / 'tests/agent/lsp/_mock_lsp_server.py'
    ws = tmp_path / 'ws'
    ws.mkdir()
    subprocess.run(['git', 'init', '-q', str(ws)], check=True)
    config = {'lsp': {'enabled': True, 'install_strategy': 'manual', 'wait_timeout': 5,
              'trusted_workspaces': [str(ws)], 'servers': {'native-probe': {
              'command': [sys.executable, str(mock)], 'extensions': ['.pnch'],
              'env': {'MOCK_LSP_SCRIPT': 'errors'}}}}}
    (tmp_path / 'config.yaml').write_text(json.dumps(config))
    from agent.lsp import shutdown_service
    shutdown_service()
    try:
        result = json.loads(model.handle_function_call('write_file',
            {'path': str(ws / 'probe.pnch'), 'content': 'hello'}, skip_tool_execution_middleware=True))
        assert not result.get('error'), result
        row = wait_receipt(tmp_path)
        assert row[0] == 'completed' and 'mock-lsp' in row[1], row
        from gateway.task_resources import ResourceGuard
        assert ResourceGuard(tmp_path / 'resources.db').held_count() == 0
    finally:
        shutdown_service()
