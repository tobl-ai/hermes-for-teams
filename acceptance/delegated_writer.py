"""Real native delegation/child tool lifecycle against a local scripted HTTP model.

No provider account or live capacity claim: requests are actual HTTP and native
child agents/tools; responses deliberately scripted for repeatable acceptance.
"""
import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
pytest.importorskip('gateway.task_resources')


def test_actual_delegated_child_writer_settles_before_following_native_write(tmp_path, monkeypatch):
    from run_agent import AIAgent
    from gateway import task_resources
    import model_tools
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setattr(task_resources, 'shared_guard_path', lambda: tmp_path / 'resources.db')
    with sqlite3.connect(tmp_path / 'native-tasks.sqlite3'):
        pass
    monkeypatch.setattr('agent.model_metadata.fetch_model_metadata', lambda *a, **kw: {})
    target = tmp_path / 'child-output'
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            messages = request.get('messages', [])
            tools = [m for m in messages if m.get('role') == 'tool']
            message = {'role': 'assistant', 'content': 'native child finished'}
            reason = 'stop'
            if not tools:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'child-write',
                    'type': 'function', 'function': {'name': 'write_file', 'arguments': json.dumps(
                    {'path': str(target), 'content': 'delegated real native write'})}}]}
                reason = 'tool_calls'
            response = {'id': 'fixture-delegation', 'object': 'chat.completion', 'created': 0, 'model': 'test',
                        'choices': [{'index': 0, 'finish_reason': reason, 'message': message}],
                        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
            content_type = 'application/json'
            if request.get('stream'):
                delta = dict(message)
                for index, tool in enumerate(delta.get('tool_calls', [])):
                    tool['index'] = index
                chunk = dict(response, object='chat.completion.chunk', choices=[
                    {'index': 0, 'finish_reason': None, 'delta': delta}])
                final = dict(response, object='chat.completion.chunk', choices=[
                    {'index': 0, 'finish_reason': reason, 'delta': {}}])
                body = ('data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(final) + '\n\ndata: [DONE]\n\n').encode()
                content_type = 'text/event-stream'
            else:
                body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    agent = AIAgent(api_key='offline-fixture', provider='custom',
        base_url=f'http://127.0.0.1:{server.server_port}/v1', model='test', api_mode='chat_completions',
        quiet_mode=True, skip_context_files=True, skip_memory=True, session_id='delegation-fixture',
        enabled_toolsets=['file'], max_iterations=5)
    try:
        result = agent._dispatch_delegate_task({'tasks': [{'goal': 'Write the fixture file then finish.'}]})
        dispatched = json.loads(result)
        from tools.async_delegation import get_durable_delegation
        deadline = time.monotonic() + 30
        while True:
            saved = get_durable_delegation(dispatched['delegation_id'])
            if saved and saved.get('completed_at'):
                break
            assert time.monotonic() < deadline, saved
            threading.Event().wait(.025)
        assert target.exists(), result
        assert target.read_text() == 'delegated real native write'
        assert requests and any(item.get('tools') for item in requests), result
        second = json.loads(model_tools.handle_function_call('write_file',
            {'path': str(tmp_path / 'following'), 'content': 'after child'}, skip_tool_execution_middleware=True))
        assert not second.get('error'), second
        assert task_resources.ResourceGuard(tmp_path / 'resources.db').held_count() == 0
    finally:
        agent.close()
        server.shutdown()
        server.server_close()
        thread.join(5)
