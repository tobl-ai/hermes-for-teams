"""Question snapshots and task lifecycle use native durable admissions, not histories."""
from dataclasses import replace

import pytest

pytest.importorskip('gateway.run')
from gateway.platforms.event import MessageEvent
from gateway.session_results import execution_result
from test_same_thread_native import setup, close


@pytest.mark.asyncio
async def test_question_snapshot_reports_completed_result_without_mutable_task_history(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    snapshots = []

    async def native_work(event, source, key, *_args):
        if event.message_id == 'question':
            child = await runner.async_session_store.get_or_create_session(source)
            snapshots.extend(await runner.async_session_store.load_transcript(child.session_id))
        execution_result.get()['result'] = {'final_response': 'contract-reviewed', 'messages': []}
        return 'contract-reviewed'

    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    try:
        await runner._handle_message(MessageEvent(text='계약서 검토', source=source, message_id='root'))
        await runner._handle_message(MessageEvent(text='현재 상황은?', source=replace(source), message_id='question'))
        text = '\n'.join(str(row.get('content', '')) for row in snapshots)
        assert 'contract-reviewed' in text
        assert 'completed' in text
        task_authority = authority._task_authority
        row = task_authority.db.execute('SELECT state FROM tasks WHERE message=?', ('root',)).fetchone()
        assert row['state'] == 'completed'
    finally:
        await close(authority)
