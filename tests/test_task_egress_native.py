"""Native task egress: actual ingress, proxy consumer and adapter boundaries."""
from dataclasses import replace
import sqlite3

import pytest
pytest.importorskip('gateway.task_egress')
from gateway.config import Platform, StreamingConfig
from gateway.platforms.base import SendResult
from gateway.platforms.event import MessageEvent
from gateway.session_results import execution_result
from test_same_thread_native import setup, close


async def branch_fixture(tmp_path, monkeypatch, *, authority_profile='default'):
    runner, authority, source = await setup(tmp_path, monkeypatch, authority_profile=authority_profile)
    captured = []
    async def native_work(event, branch_source, *_args):
        captured.append(replace(branch_source))
        execution_result.get()['result'] = {'final_response': 'done', 'messages': []}
        return 'done'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    await runner._handle_message(MessageEvent(text='계약서 검토해 줘', message_id='origin-A', source=source))
    return runner, authority, source, captured[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('native_home_identity',[False,True])
async def test_proxy_stream_keeps_native_task_label_and_original_anchor(tmp_path, monkeypatch,native_home_identity):
    runner, authority, source, branch = await branch_fixture(tmp_path, monkeypatch,
        authority_profile=str(tmp_path) if native_home_identity else 'default')
    seen = []
    async def send(chat_id, content, **kwargs):
        seen.append((content, kwargs))
        return SendResult(success=True, message_id='stream-first')
    async def edit_message(chat_id, message_id, content, **kwargs):
        seen.append((content, dict(kwargs, message_id=message_id)))
        return SendResult(success=True, message_id=message_id)
    monkeypatch.setattr(runner.adapters[Platform.TELEGRAM], 'send', send)
    monkeypatch.setattr(runner.adapters[Platform.TELEGRAM], 'edit_message', edit_message)
    monkeypatch.setattr('gateway.run._load_gateway_config', lambda: {})
    runner.config.streaming = StreamingConfig(enabled=True, transport='edit', edit_interval=0, buffer_threshold=1)
    try:
        consumer = runner._proxy_stream_consumer(branch, 'followup-A', {}, lambda: True)
        assert consumer is not None
        await consumer._send_or_edit('first streamed words')
        assert '계약서' in seen[0][0] and 'origin-A' in seen[0][0], seen
        assert seen[0][1].get('reply_to') == 'origin-A', seen
        await consumer._send_or_edit('first streamed words plus more')
        assert seen[1][0].startswith(seen[0][0]), seen
        assert seen[1][1]['message_id'] == 'stream-first'
        with sqlite3.connect(tmp_path / 'native-tasks.sqlite3') as db:
            assert db.execute('SELECT task FROM reply_bindings WHERE message=?', ('stream-first',)).fetchone()[0] == branch.task_branch
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_all_text_transports_use_one_root_binding_and_receipts(tmp_path, monkeypatch):
    runner, authority, source, branch = await branch_fixture(tmp_path, monkeypatch)
    adapter = runner.adapters[Platform.TELEGRAM]
    seen = []
    async def send(chat_id, content, **kwargs):
        seen.append(('send', content, kwargs))
        return SendResult(success=True, message_id='owned')
    async def edit_message(chat_id, message_id, content, **kwargs):
        seen.append(('edit', content, kwargs))
        return SendResult(success=True, message_id=message_id)
    async def send_stream_frame(content, *, chat_id, reply_to=None, **kwargs):
        seen.append(('native', content, dict(kwargs, reply_to=reply_to)))
        return True
    async def send_draft(chat_id, draft_id, content, metadata=None):
        seen.append(('draft', content, metadata))
        return True
    for name, fn in [('send', send), ('edit_message', edit_message), ('send_stream_frame', send_stream_frame), ('send_draft', send_draft)]:
        monkeypatch.setattr(adapter, name, fn, raising=False)
    try:
        bound = runner._task_delivery_adapter_for(branch)
        assert isinstance(bound, type(adapter))
        await bound.send(source.chat_id, 'commentary', reply_to='followup-A')
        await bound.edit_message(source.chat_id, 'owned', 'final')
        await bound.send_stream_frame('one', chat_id=source.chat_id, reply_to='followup-A', turn_id='turn')
        await bound.send_stream_frame('one two', chat_id=source.chat_id, reply_to='followup-A', turn_id='turn')
        await bound.send_draft(source.chat_id, 1, 'draft', metadata={'telegram_reply_to_message_id': 'followup-A'})
        for kind, text, kwargs in seen:
            assert '계약서' in text and 'origin-A' in text
            if kind in {'send', 'native'}:
                assert kwargs['reply_to'] == 'origin-A'
        assert seen[3][1].startswith(seen[2][1])
        assert seen[4][2]['telegram_reply_to_message_id'] == 'origin-A'
        # A recovered source re-resolves the same durable owner, not an ambient id.
        restored = type(branch).from_dict(branch.to_dict())
        await runner._task_delivery_adapter_for(restored).send(source.chat_id, 'recovered')
        assert seen[-1][2]['reply_to'] == 'origin-A'
        count = len(seen)
        for wrong in (replace(branch, chat_id='other-room'), replace(branch, user_id='bob'),
                      replace(branch, profile='other'), replace(branch, task_branch='not-a-task')):
            with pytest.raises(RuntimeError):
                runner._task_delivery_adapter_for(wrong)
        with pytest.raises(RuntimeError):
            await bound.send('other-room', 'must not send')
        with pytest.raises(RuntimeError):
            await bound.edit_message(source.chat_id, 'someone-elses-message', 'must not edit')
        assert len(seen) == count
        assert runner._task_delivery_adapter_for(source) is adapter
        await runner._task_delivery_adapter_for(source).send(source.chat_id, 'ordinary', reply_to='ordinary-anchor')
        assert seen[-1][1:] == ('ordinary', {'reply_to': 'ordinary-anchor'})
    finally:
        await close(authority)
