"""Actual concurrent native interaction renderers retain task identity and root."""
import asyncio
from dataclasses import replace
import sqlite3

import pytest
pytest.importorskip('gateway.task_egress')
from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent
from gateway.session_results import execution_result
from test_task_egress_native import branch_fixture
from test_same_thread_native import close


@pytest.mark.asyncio
async def test_two_task_clarify_and_native_approval_keep_root_label_and_callbacks(tmp_path,monkeypatch):
    runner,authority,source,branch_a=await branch_fixture(tmp_path,monkeypatch)
    captured=[]
    async def native_work(event,branch,*args):
        captured.append(replace(branch))
        execution_result.get()['result']={'final_response':'done','messages':[]}
        return 'done'
    monkeypatch.setattr(runner,'_handle_message_with_agent',native_work)
    await runner._handle_message(MessageEvent(text='별도로 보고서 작성해 줘',message_id='origin-B',source=replace(source)))
    branch_b=captured[0]
    adapter=runner.adapters[Platform.TELEGRAM]
    seen=[]; prompts=[]
    async def send(chat_id,content,**kwargs):
        seen.append((content,kwargs))
        return SendResult(success=True,message_id='clarify-'+str(len(seen)))
    async def native_approval(self,prompt):
        prompts.append(prompt)
        return SendResult(success=True,message_id='approval-'+str(len(prompts)))
    monkeypatch.setattr(adapter,'send',send)
    monkeypatch.setattr(type(adapter),'send_clarify',BasePlatformAdapter.send_clarify)
    monkeypatch.setattr(type(adapter),'_send_exec_approval_prompt',native_approval)
    try:
        a=runner._task_delivery_adapter_for(branch_a); b=runner._task_delivery_adapter_for(branch_b)
        await asyncio.gather(a.send_clarify(source.chat_id,'Choose A',None,'clarify-A','session-A'),
                             b.send_clarify(source.chat_id,'Choose B',None,'clarify-B','session-B'))
        for index,anchor in enumerate(['origin-A','origin-B']):
            assert seen[index][0].startswith('[') and anchor in seen[index][0],seen
            assert seen[index][1]['reply_to']==anchor,seen
        await asyncio.gather(a.send_exec_approval(source.chat_id,'printf A','session-A',request_id='approval-A'),
                             b.send_exec_approval(source.chat_id,'printf B','session-B',request_id='approval-B'))
        for index,anchor in enumerate(['origin-A','origin-B']):
            prompt=prompts[index]
            assert prompt.text.startswith('[') and anchor in prompt.text,prompt
            assert prompt.metadata['reply_to_message_id']==anchor
            assert prompt.command==('printf A' if index==0 else 'printf B')
            assert prompt.session_key==('session-A' if index==0 else 'session-B')
            assert prompt.request_id==('approval-A' if index==0 else 'approval-B')
        with sqlite3.connect(tmp_path/'native-tasks.sqlite3') as db:
            rows=db.execute("SELECT task,message FROM reply_bindings WHERE message LIKE 'clarify-%' OR message LIKE 'approval-%'").fetchall()
        assert len(rows)==4 and {row[0] for row in rows}=={branch_a.task_branch,branch_b.task_branch},rows
    finally:
        await close(authority)
