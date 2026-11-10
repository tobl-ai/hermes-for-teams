"""Fresh-process capability and actual agent-loop bounded question regressions."""
import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
pytest.importorskip('gateway.run')


def ledger_for(home):
    ledger = home / 'native-tasks.sqlite3'
    with sqlite3.connect(ledger) as db:
        db.executescript('CREATE TABLE tasks(id,room,sender,message,session); '
                         'CREATE TABLE decisions(task,room,sender,message,intent);')
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', ('task', 'room', 'alice', 'msg', 'session'))
        db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)', ('task', 'room', 'alice', 'msg', 'question'))
    return ledger


@pytest.mark.parametrize('session,denied', [('session', True), ('ordinary', False)])
def test_managed_fresh_process_reads_owner_creation_decision(tmp_path, session, denied):
    ledger_for(tmp_path)
    frame = {'home': str(tmp_path), 'policy': {'request_json': json.dumps({'turn_v1':
        {'finite': False, 'unattended': False, 'yolo': False}})},
        'scope': {'execution_id': 'admission-worker:test', 'session_id': session}, 'route': 'test'}
    child = '''import json,sys
from gateway.session_managed_worker import worker_turn_scope
from gateway.question_authority import question_tool_denial
with worker_turn_scope(json.loads(sys.argv[1])):
    print(json.dumps({'denied':bool(question_tool_denial('terminal'))}))
assert question_tool_denial('terminal') is None
'''
    result = subprocess.run([sys.executable, '-c', child, json.dumps(frame)],
                            env=os.environ.copy(), capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(result.stdout)['denied'] is denied


@pytest.mark.parametrize('response_mode', ['forbidden_tools', 'length_continuation', 'stalled'])
def test_actual_agent_loop_repeated_forbidden_tools_has_small_call_bound(tmp_path, monkeypatch, response_mode):
    from run_agent import AIAgent
    from gateway.question_authority import question_execution_scope, QUESTION_CALLS
    requests = []
    stall = threading.Event()
    if response_mode == 'stalled':
        monkeypatch.setattr('gateway.question_authority.QUESTION_SECONDS', 1.0)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if response_mode == 'stalled' and len(requests) == 1:
                stall.wait(5)
            response = {'id': 'chatcmpl-test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
                'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                    'content': None, 'tool_calls': [{'id': f'call-{len(requests)}', 'type': 'function',
                    'function': {'name': 'terminal', 'arguments': '{"command":"touch forbidden"}'}}]}}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
            if response_mode in {'length_continuation', 'stalled'}:
                response['choices'] = [{'index': 0, 'finish_reason': 'length' if len(requests) == 1 else 'stop',
                    'message': {'role': 'assistant', 'content': 'Python is a programming language.'}}]
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the question deadline closed this fixture connection
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setattr('agent.model_metadata.fetch_model_metadata', lambda *a, **kw: {})
    monkeypatch.setattr('model_tools.get_tool_definitions', lambda *a, **kw: [])
    monkeypatch.setattr('model_tools.check_toolset_requirements', lambda *a, **kw: {})
    agent = AIAgent(api_key='offline-fixture', provider='custom',
        base_url=f'http://127.0.0.1:{server.server_port}/v1', model='test', api_mode='chat_completions',
        quiet_mode=True, skip_context_files=True, skip_memory=True, session_id='question-loop', max_iterations=100)
    before = agent.max_iterations
    requests.clear()  # constructor metadata probes are not question execution
    try:
        ledger = ledger_for(tmp_path)
        with question_execution_scope(ledger, 'session'):
            result = agent.run_conversation('파이썬은 뭐야?')
        assert 0 < len(requests) <= QUESTION_CALLS, result
        assert all(not item.get('tools') for item in requests)
        assert all(0 < item.get('max_tokens', item.get('max_completion_tokens', 0)) <= 2048 for item in requests)
        assert agent.max_iterations == before
        assert not (tmp_path / 'forbidden').exists()
        if response_mode == 'stalled':
            assert result.get('interrupted') or result.get('failed'), result
            stall.set()
            monkeypatch.setattr('gateway.question_authority.QUESTION_SECONDS', 10.0)
            with question_execution_scope(ledger, 'session'):
                second = agent.run_conversation('다시 설명해 줘')
            assert 'Python is a programming language.' in (second.get('final_response') or ''), second
    finally:
        stall.set()
        server.shutdown()
        server.server_close()
        thread.join(5)
        agent.close()
