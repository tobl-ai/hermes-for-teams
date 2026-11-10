"""Real owner daemon -> managed worker -> persistent kernel -> native file writer."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest
pytest.importorskip('gateway.task_resources')
from tests.gateway.fixtures.local_recovery_probe import daemon, rpc, websocket
from tests.waiting import async_wait_until


def test_real_managed_worker_kernel_then_file_writer(tmp_path):
    import tools.code_kernel
    core = Path(tools.code_kernel.__file__).resolve().parents[1]
    home, user = tmp_path / 'state', tmp_path / 'user'
    home.mkdir(); user.mkdir()
    (home / 'tmp').mkdir()
    target = home / 'managed-output'
    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            messages = request.get('messages', [])
            latest = max((i for i,m in enumerate(messages) if m.get('role') == 'user'), default=-1)
            tools = [m for m in messages[latest+1:] if m.get('role') == 'tool']
            if latest < 0:
                message = {'role': 'assistant', 'content': 'metadata'}
            elif not tools:
                message = self.tool('execute_code', {'code': 'value = {"managed": [1, 2]}\nprint(value)'}, 'kernel')
            elif len(tools) == 1:
                message = self.tool('write_file', {'path': str(target), 'content': 'managed native writer'}, 'file')
            else:
                message = {'role': 'assistant', 'content': 'MANAGED_WRITER_DONE'}
            frame = {'id': 'managed-fixture', 'model': 'managed-model', 'choices': [{'index':0,
                'message':message, 'finish_reason':'tool_calls' if message.get('tool_calls') else 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
            kind = 'application/json'
            if request.get('stream'):
                choice = frame['choices'][0]
                choice['delta'] = choice.pop('message')
                for index, call in enumerate(choice['delta'].get('tool_calls', [])):
                    call['index'] = index
                payload = ('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n\n').encode()
                kind = 'text/event-stream'
            else:
                payload = json.dumps(frame).encode()
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        @staticmethod
        def tool(name, args, ident):
            return {'role':'assistant','content':None,'tool_calls':[{'id':ident,'type':'function',
                    'function':{'name':name,'arguments':json.dumps(args)}}]}
    peer = ThreadingHTTPServer(('127.0.0.1',0),Model)
    thread = threading.Thread(target=peer.serve_forever,daemon=True); thread.start()
    url = f'http://127.0.0.1:{peer.server_port}/v1'
    config = {'gateway':{'multiplex_profiles':False,'managed_workers':True},
              'model':{'provider':'custom','default':'managed-model','base_url':url},
              'approvals':{'mode':'manual'},
              'auxiliary':{'title_generation':{'enabled':False}},
              'platform_toolsets':{'cli':['file','code_execution']}}
    (home / 'config.yaml').write_text(json.dumps(config))
    with sqlite3.connect(home / 'native-tasks.sqlite3') as db:
        db.executescript('CREATE TABLE tasks(id,room,sender,message,session); CREATE TABLE decisions(task,room,sender,message,intent);')
    env = {k:os.environ[k] for k in ('PATH','LANG','TZ') if k in os.environ}
    env.update(HOME=str(user),USERPROFILE=str(user),HERMES_HOME=str(home),PYTHONPATH=str(core),
               TMPDIR=str(home/'tmp'),OPENAI_API_KEY='loopback-only',OPENAI_BASE_URL=url)
    resource_db = user / '.local/state/hermes/locks/native-task-resources.sqlite3'
    def query(sql):
        with sqlite3.connect(f'file:{home / "state.db"}?mode=ro',uri=True) as db:
            return db.execute(sql).fetchall()
    async def exercise(desc):
        async with websocket(home,desc) as ws:
            created = await rpc(ws,'session.create',request_id='managed',source='cli',cwd=str(home),
                                model='managed-model',provider='custom',base_url=url,api_key='loopback-only',
                                toolsets=['file','code_execution'],ignore_rules=True)
            assert 'result' in created, created
            sid=created['result']['session_id']
            submitted=await rpc(ws,'prompt.submit',session_id=sid,input_id='managed-write',text='RUN_MANAGED_KERNEL_AND_WRITER')
            assert 'result' in submitted,submitted
            deadline = time.monotonic() + 60
            answered = set()
            while query("SELECT status FROM session_admissions WHERE request_id='managed-write'") != [('terminal',)]:
                snapshot = await rpc(ws,'session.resume',session_id=sid)
                for prompt in snapshot.get('result',{}).get('prompts',[]):
                    if prompt['kind']=='approval' and prompt['prompt_id'] not in answered:
                        response = await rpc(ws,'approval.respond',session_id=sid,
                            execution_generation=prompt['execution_generation'],prompt_id=prompt['prompt_id'],choice='once')
                        assert response.get('result',{}).get('status')=='resolved',response
                        answered.add(prompt['prompt_id'])
                assert time.monotonic()<deadline,snapshot
                await asyncio.sleep(.05)
            restored=await rpc(ws,'session.resume',session_id=sid)
            assert 'MANAGED_WRITER_DONE' in json.dumps(restored), restored
            assert target.read_text()=='managed native writer'
            assert query('SELECT status FROM worker_executions')==[('terminal',)]
    try:
        with daemon(core,home,env,barrier=False) as (owner,desc):
            asyncio.run(exercise(desc))
        # Derive the backend's canonical rendezvous path, without guessing a directory name.
        import subprocess
        probe=subprocess.run([sys.executable,'-c','from gateway.task_resources import shared_guard_path; print(shared_guard_path())'],
                             cwd=core,env=env,capture_output=True,text=True,check=True,timeout=10)
        resource_db=Path(probe.stdout.strip())
        with sqlite3.connect(f'file:{resource_db}?mode=ro',uri=True) as db:
            assert db.execute('SELECT COUNT(*) FROM reservations').fetchone()==(0,)
    finally:
        peer.shutdown();peer.server_close();thread.join(5)
