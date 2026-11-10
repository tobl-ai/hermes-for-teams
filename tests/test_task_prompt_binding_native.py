"""Real native sender route binds delivered prompt IDs, never untrusted text IDs."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
import pytest
pytest.importorskip('gateway.task_resources')
from test_same_thread_native import setup, close
from gateway.platforms.event import MessageEvent
from gateway.platforms.base import SendResult
from gateway.run_turn_progress import GatewayTurnProgressMixin
from gateway.session_results import execution_result


def test_missing_loop_closes_unstarted_send():
    import inspect
    async def send():
        return SendResult(success=True, message_id='unused')
    coro = send()
    ctx = SimpleNamespace(source=None, _loop_for_step=None)
    assert GatewayTurnProgressMixin._schedule(SimpleNamespace(_ctx=ctx), coro, 'no loop') is None
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


@pytest.mark.asyncio
async def test_delivered_prompt_reply_targets_only_its_task(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    started, release = asyncio.Event(), asyncio.Event()
    async def work(event, *_args):
        execution_result.get()['result'] = {'final_response': 'done', 'messages': []}
        if event.message_id == 'root':
            ctx = SimpleNamespace(source=event.source, _loop_for_step=asyncio.get_running_loop())
            sender = SimpleNamespace(_ctx=ctx)
            async def send():
                return SendResult(success=True, message_id='bot-approval')
            fut = GatewayTurnProgressMixin._schedule(sender, send(), 'test')
            await asyncio.wrap_future(fut)
            started.set()
            await release.wait()
        return 'done'
    monkeypatch.setattr(runner, '_handle_message_with_agent', work)
    approvals = []
    async def approve(event):
        approvals.append(event.source.task_branch)
        return 'approved'
    monkeypatch.setattr(runner, '_handle_approve_command', approve)
    task = asyncio.create_task(runner._handle_message(MessageEvent(text='계약서 검토해 줘', source=source, message_id='root')))
    try:
        await asyncio.wait_for(started.wait(), 8)
        response = await asyncio.wait_for(runner._handle_message(MessageEvent(
            text='/approve', source=replace(source), message_id='answer', reply_to_message_id='bot-approval')), 1)
        assert 'approved' in response
        assert len(approvals) == 1
        await runner._handle_message(MessageEvent(text='/approve', source=replace(source, user_id='bob'),
                                                message_id='other', reply_to_message_id='bot-approval'))
        assert len(approvals) == 1
    finally:
        release.set()
        await close(authority, [task])
