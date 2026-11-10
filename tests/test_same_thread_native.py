"""Native task acceptance; synthetic final executor, no provider/platform I/O.

Run with scripts/verify_automatic.py and an exact disposable core. Core availability
is optional in the dependency-free add-on unit lane, mandatory in the native lane.
"""
import asyncio
from dataclasses import replace

import pytest

pytest.importorskip('gateway.run')
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from gateway.session_authority import initialize_session_authority
from gateway.session_results import execution_result
from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
from hermes_for_teams.plugin import register


class Adapter(BasePlatformAdapter):
    async def connect(self):
        return True
    async def disconnect(self):
        pass
    async def send(self, *args, **kwargs):
        return SendResult(success=True, message_id='reply')
    async def send_typing(self, *args, **kwargs):
        pass
    async def get_chat_info(self, chat_id):
        return {'id': chat_id}


async def setup(tmp_path, monkeypatch, *, authority_profile='default'):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('TELEGRAM_ALLOWED_USERS', 'alice,bob')
    monkeypatch.setenv('GATEWAY_ALLOW_ALL_USERS', 'false')
    runner = GatewayRunner(GatewayConfig(sessions_dir=tmp_path / 'sessions',
                                        group_sessions_per_user=False))
    adapter = Adapter(PlatformConfig(enabled=True), Platform.TELEGRAM)
    runner.adapters = {Platform.TELEGRAM: adapter}
    authority = await initialize_session_authority(runner, profile_id=authority_profile, instance_id='tasks-offline')
    manager = get_plugin_manager()
    monkeypatch.setattr(manager, '_middleware', {})
    manager._discovered = True
    ctx = PluginContext(PluginManifest(name='hermes-for-teams'), manager)
    ctx.set_config('same_thread_enabled', True)
    ctx.set_config('automatic_interactive', 8)
    register(ctx)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='shared-room',
                           chat_type='group', user_id='alice')
    return runner, authority, source


async def close(authority, tasks=()):
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.gather(*(live.task for live in authority.sessions.values() if live.task), return_exceptions=True)
    if getattr(authority, '_task_authority', None):
        authority._task_authority.db.close()
    authority.db.close()


@pytest.mark.asyncio
async def test_ordinary_same_room_independent_requests_overlap(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    a_started, b_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []

    async def native_work(event, source, key, *_args, **_kwargs):
        seen.append((event.message_id, key, source.user_id, source.chat_id))
        (a_started if event.message_id == 'A' else b_started).set()
        await release.wait()
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id

    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    tasks = []
    try:
        tasks.append(asyncio.create_task(runner._handle_message(MessageEvent(
            text='계약서 검토해 줘', message_id='A', source=source))))
        await asyncio.wait_for(a_started.wait(), 8)
        tasks.append(asyncio.create_task(runner._handle_message(MessageEvent(
            text='별도로 내일 발표 자료도 만들어 줘', message_id='B', source=replace(source)))))
        await asyncio.wait_for(b_started.wait(), 3)
        assert len({row[1] for row in seen}) == 2
        assert all(row[2:] == ('alice', 'shared-room') for row in seen)
    finally:
        release.set()
        await close(authority, tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['했어?', '현재 상황은?', '파이썬은 뭐야?'])
async def test_questions_reply_before_coding_finishes(tmp_path, monkeypatch, question):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    started, release = asyncio.Event(), asyncio.Event()
    keys = []
    async def native_work(event, source, key, *_args):
        keys.append(key)
        if event.message_id == 'coding':
            started.set()
            await release.wait()
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    task = asyncio.create_task(runner._handle_message(MessageEvent(
        text='계약서 검토해 줘', source=source, message_id='coding')))
    try:
        await asyncio.wait_for(started.wait(), 8)
        reply = await asyncio.wait_for(runner._handle_message(MessageEvent(
            text=question, source=replace(source), message_id='question')), 3)
        assert 'question' in reply
        assert not task.done()
        assert len(set(keys)) == 2
    finally:
        release.set()
        await close(authority, [task])


@pytest.mark.asyncio
async def test_actual_adapter_burst_preserves_independent_requests_while_delivery_waits(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    adapter = runner.adapters[Platform.TELEGRAM]
    adapter.set_message_handler(runner._handle_message)
    adapter.config.extra['group_sessions_per_user'] = False
    entered, release_delivery = asyncio.Event(), asyncio.Event()
    seen, sent = [], []
    async def native_work(event, *_args):
        seen.append(event.message_id)
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id
    async def send(chat_id, content, **kwargs):
        sent.append(content)
        if 'first' in content:
            entered.set()
            await release_delivery.wait()
        return SendResult(success=True, message_id='reply-' + str(len(sent)))
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    monkeypatch.setattr(adapter, 'send', send)
    from tests.waiting import async_wait_until
    try:
        await adapter.handle_message(MessageEvent(text='계약서 검토', source=source, message_id='first'))
        await asyncio.wait_for(entered.wait(), 8)
        for message, text in [('second', '별도로 발표 자료'), ('third', '별도로 보고서')]:
            adapter._enqueue_text_event(MessageEvent(text=text, source=replace(source), message_id=message))
        await async_wait_until(lambda: len(seen) == 3, timeout=4, what='three independent ingress messages')
        assert set(seen) == {'first', 'second', 'third'}
        assert not release_delivery.is_set()
    finally:
        release_delivery.set()
        await close(authority)
        pending = list(adapter._pending_text_batch_tasks.values())
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(.1)


@pytest.mark.asyncio
async def test_targeted_clarify_reply_is_not_queued_behind_waiting_worker(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    from tools import clarify_gateway
    from tests.waiting import async_wait_until
    started, release = asyncio.Event(), asyncio.Event()
    entries = []
    async def native_work(event, source, key, *_args):
        if event.message_id == 'root':
            entries.append(clarify_gateway.register('task-question', key, '기간?', None))
            started.set()
            await async_wait_until(lambda: entries[0].event.is_set() or release.is_set(), timeout=10, what='clarify reply')
        execution_result.get()['result'] = {'final_response': 'ok', 'messages': []}
        return 'ok'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    task = asyncio.create_task(runner._handle_message(MessageEvent(text='계약서 검토', source=source, message_id='root')))
    reply_task = None
    try:
        await asyncio.wait_for(started.wait(), 8)
        reply_task = asyncio.create_task(runner._handle_message(MessageEvent(text='6개월', source=replace(source),
                                      message_id='answer', reply_to_message_id='root')))
        await asyncio.wait_for(asyncio.shield(reply_task), 2)
        assert entries[0].response == '6개월'
    finally:
        release.set()
        clarify_gateway.resolve_gateway_clarify('task-question', 'cleanup')
        await close(authority, [task] + ([reply_task] if reply_task else []))
        clarify_gateway.wait_for_response('task-question', .01)


@pytest.mark.asyncio
async def test_followup_routing_decision_survives_new_ambiguous_task(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    from gateway.task_routing import TaskAuthority
    from hermes_for_teams.task_routing import classify
    tasks = TaskAuthority(runner, authority)
    async def initialize(event, row):
        pass
    monkeypatch.setattr(tasks, 'create_branch', initialize)
    room = runner._session_key_for_source(source)
    try:
        first, _ = await tasks.prepare(MessageEvent(text='계약서 검토', source=source, message_id='root'), room, classify)
        event = MessageEvent(text='계약서는 수정해', source=replace(source), message_id='edit')
        assert (await tasks.prepare(event, room, classify))[0]['id'] == first['id']
        await tasks.prepare(MessageEvent(text='별도로 계약서 검토', source=replace(source), message_id='other'), room, classify)
        row, intent = await tasks.prepare(event, room, classify)
        assert row is not None and row['id'] == first['id']
        assert intent == 'followup'
    finally:
        tasks.db.close()
        await close(authority)


@pytest.mark.asyncio
async def test_snapshot_initialized_on_inserted_task_not_message_sort_order(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    from gateway.task_routing import TaskAuthority
    from hermes_for_teams.task_routing import classify
    tasks = TaskAuthority(runner, authority)
    initialized = []
    async def initialize(event, row):
        initialized.append((event.message_id, row['id'], row['message']))
    monkeypatch.setattr(tasks, 'create_branch', initialize)
    room = runner._session_key_for_source(source)
    try:
        first, _ = await tasks.prepare(MessageEvent(text='계약서 검토', source=source, message_id='Z'), room, classify)
        second, _ = await tasks.prepare(MessageEvent(text='별도로 발표 자료', source=replace(source), message_id='A'), room, classify)
        assert initialized == [('Z', first['id'], 'Z'), ('A', second['id'], 'A')]
    finally:
        tasks.db.close()
        await close(authority)


@pytest.mark.asyncio
async def test_ten_native_tasks_are_bounded_to_eight_interactive_seats(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    gate = asyncio.Event()
    active = peak = 0
    async def native_work(event, *_args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await gate.wait()
            execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
            return event.message_id
        finally:
            active -= 1
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    tasks = [asyncio.create_task(runner._handle_message(MessageEvent(
        text=f'별도로 작업 {i}', message_id=f'capacity-{i}', source=replace(source)))) for i in range(10)]
    try:
        from tests.waiting import async_wait_until
        await async_wait_until(lambda: len(authority.executing) == 10, timeout=8, what='ten admitted branches')
        gate.set()
        replies = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert all(replies)
        assert peak == 8
    finally:
        gate.set()
        await close(authority, tasks)


@pytest.mark.asyncio
async def test_native_admission_keeps_original_callback_event_and_marker(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    from gateway import session_envelope
    event = MessageEvent(text='계약서 검토', source=source, message_id='original')
    event._turn_marker_handoff = True
    captured = []
    original = session_envelope.prepare_native
    async def prepare(runner_arg, candidate):
        captured.append(candidate)
        return await original(runner_arg, candidate)
    monkeypatch.setattr(session_envelope, 'prepare_native', prepare)
    async def native_work(event, *_args):
        execution_result.get()['result'] = {'final_response': 'ok', 'messages': []}
        return 'ok'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    try:
        assert await runner._handle_message(event)
        assert captured == [event]
        assert captured[0] is event
        assert captured[0]._turn_marker_handoff is True
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_control_disabled_event_cannot_cancel_its_task(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    async def native_work(event, *_args):
        execution_result.get()['result'] = {'final_response': 'ok', 'messages': []}
        return 'ok'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    stops = []
    async def stop(event):
        stops.append(event)
        return 'stopped'
    monkeypatch.setattr(runner, '_handle_stop_command', stop)
    try:
        await runner._handle_message(MessageEvent(text='계약서 검토', source=source, message_id='first'))
        await runner._handle_message(MessageEvent(text='계약서 멈춰', source=replace(source),
                                                  message_id='control', allow_gateway_control=False))
        assert not stops
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_idle_task_stop_never_scans_or_interrupts_other_chat_tasks(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    async def native_work(event, *_args):
        execution_result.get()['result'] = {'final_response': 'ok', 'messages': []}
        return 'ok'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    def forbidden(*args):
        raise AssertionError('A task stop must never scan the room for other work')
    monkeypatch.setattr(runner, '_same_chat_runs', forbidden)
    try:
        await runner._handle_message(MessageEvent(text='계약서 검토', source=source, message_id='first'))
        assert await runner._handle_message(MessageEvent(text='계약서 멈춰', source=replace(source), message_id='cancel'))
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_stop_delivery_dedup_is_durable_before_side_effect(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    async def native_work(event, *_args):
        execution_result.get()['result'] = {'final_response': 'ok', 'messages': []}
        return 'ok'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    calls = []
    original = runner._hm_stop_owner_turn
    async def stop(key):
        calls.append(key)
        return await original(key)
    monkeypatch.setattr(runner, '_hm_stop_owner_turn', stop)
    try:
        await runner._handle_message(MessageEvent(text='계약서 검토', source=source, message_id='first'))
        for _ in range(2):
            await runner._handle_message(MessageEvent(text='계약서 멈춰', source=replace(source), message_id='cancel', reply_to_message_id='first'))
        assert len(calls) == 1
        assert ':task:' in calls[0]
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_result_label_and_root_anchor_are_durable_for_recovered_delivery(tmp_path, monkeypatch):
    runner, authority, source = await setup(tmp_path, monkeypatch)
    async def native_work(event, *_args):
        execution_result.get()['result'] = {'final_response': 'native answer', 'messages': []}
        return 'native answer'
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    from hermes_state_runtime import list_session_admissions
    try:
        response = await runner._handle_message(MessageEvent(text='계약서 검토', source=source, message_id='first'))
        rows = [r for sid in authority.sessions for r in list_session_admissions(authority.db, session_id=sid, pending_only=False)]
        assert len(rows) == 1
        from gateway.session_results import admission_result
        saved = admission_result(authority.db, rows[0]['admission_id'])
        assert saved['result']['final_response'] == response
        assert '계약서' in response and 'first' in response
        assert rows[0]['payload']['native_text_v1']['event']['reply_anchor_override'] == 'first'
    finally:
        await close(authority)
