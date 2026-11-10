"""Saturation acceptance via ordinary native ingress, not scheduler-only tests."""
import asyncio
from dataclasses import replace
import pytest
pytest.importorskip('gateway.task_resources')
from test_same_thread_native import setup, close
from gateway.platforms.event import MessageEvent
from gateway.session_results import execution_result


@pytest.mark.asyncio
async def test_saturated_work_still_answers_question(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    release = asyncio.Event()
    started = set()
    async def work(event, *_args):
        if event.message_id != 'q':
            started.add(event.message_id)
            await release.wait()
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id
    monkeypatch.setattr(runner, '_handle_message_with_agent', work)
    tasks = [asyncio.create_task(runner._handle_message(MessageEvent(
        text=f'별도로 작업 {i} 수행해', message_id=f'job-{i}', source=replace(source)))) for i in range(8)]
    try:
        async def full():
            while len(started) < 8:
                await asyncio.sleep(.01)
        await asyncio.wait_for(full(), 8)
        result = await asyncio.wait_for(runner._handle_message(MessageEvent(
            text='현재 상황은?', message_id='q', source=replace(source))), 1)
        assert 'q' in result
        assert all(not task.done() for task in tasks)
    finally:
        release.set()
        await close(authority, tasks)
