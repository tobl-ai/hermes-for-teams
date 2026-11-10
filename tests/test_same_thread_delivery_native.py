"""Task transport-envelope lifecycle contracts on the real native ingress."""
import asyncio
from dataclasses import replace

import pytest

pytest.importorskip('gateway.run')
from gateway.config import Platform
from gateway.platforms.base import SendResult
from gateway.platforms.event import MessageEvent
from gateway.session_results import execution_result
from test_same_thread_native import setup, close


@pytest.mark.asyncio
async def test_each_task_envelope_runs_its_own_post_delivery_callback(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    adapter = runner.adapters[Platform.TELEGRAM]
    adapter.set_message_handler(runner._handle_message)
    adapter.config.extra['group_sessions_per_user'] = False
    entered, release = asyncio.Event(), asyncio.Event()
    fired = []

    async def native_work(event, source, key, *_args):
        message = event.message_id
        adapter.register_post_delivery_callback(key, lambda: fired.append(message), generation=1)
        execution_result.get()['result'] = {'final_response': message, 'messages': []}
        return message

    async def send(chat_id, content, **kwargs):
        if 'first' in content:
            entered.set()
            await release.wait()
        return SendResult(success=True, message_id='reply')

    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    monkeypatch.setattr(adapter, 'send', send)
    from tests.waiting import async_wait_until
    try:
        await adapter.handle_message(MessageEvent(text='계약서 검토', source=source, message_id='first'))
        await asyncio.wait_for(entered.wait(), 8)
        await adapter.handle_message(MessageEvent(text='별도로 보고서', source=replace(source), message_id='second'))
        await async_wait_until(lambda: fired == ['second'], timeout=3, what='second delivery callback')
        assert not release.is_set()
        release.set()
        await async_wait_until(lambda: fired == ['second', 'first'], timeout=3, what='first delivery callback')
        assert not adapter._post_delivery_callbacks
    finally:
        release.set()
        await close(authority)
        await asyncio.gather(*list(adapter._background_tasks), return_exceptions=True)
