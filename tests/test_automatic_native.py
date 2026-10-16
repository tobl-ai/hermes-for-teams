"""Offline native ingress + durable authority + addon integration.

Only final agent work is synthetic; no live platform/provider request.
Run with scripts/verify_automatic.py and the separate seam worktree.
"""
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip('gateway.turn_scheduling')
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from gateway.session_authority import initialize_session_authority
from gateway.session_results import execution_result
from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager
from hermes_for_teams.plugin import register as register_plugin
from hermes_state_runtime import list_session_admissions


class Adapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True), Platform.TELEGRAM)
    async def connect(self, **kwargs):
        return True
    async def disconnect(self):
        pass
    async def send(self, *args, **kwargs):
        return SendResult(success=True, message_id='fixture-reply')
    async def send_typing(self, *args, **kwargs):
        pass
    async def get_chat_info(self, chat_id):
        return {'id': chat_id}


async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('TELEGRAM_ALLOWED_USERS', 'alice,bob')
    monkeypatch.setenv('GATEWAY_ALLOW_ALL_USERS', 'false')
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    runner = GatewayRunner(GatewayConfig(sessions_dir=tmp_path / 'sessions', group_sessions_per_user=False))
    adapter = Adapter()
    runner.adapters = {Platform.TELEGRAM: adapter}
    authority = await initialize_session_authority(runner, profile_id='default', instance_id='offline')
    manager = get_plugin_manager()
    monkeypatch.setattr(manager, '_middleware', {})
    manager._discovered = True
    ctx = PluginContext(PluginManifest(name='hermes-for-teams'), manager)
    ctx.set_config('automatic_enabled', True)
    ctx.set_config('automatic_interactive', 1)
    ctx.set_config('automatic_background', 1)
    ctx.set_config('automatic_heavy_bytes', 100)
    register_plugin(ctx)
    assert len(manager._middleware['gateway_turn_execution']) == 1
    return runner, authority


@pytest.mark.asyncio
async def test_ordinary_ingress_fifo_parallel_dedupe_source_media(tmp_path, monkeypatch):
    runner, authority = await setup(tmp_path, monkeypatch)
    heavy_gate, heavy_started = asyncio.Event(), asyncio.Event()
    seen = []
    media = tmp_path / 'ordinary.txt'
    media.write_text('original-attachment')
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='group', chat_type='group', user_id='alice', user_name='Alice')
    other = replace(source, chat_id='independent', user_id='bob', user_name='Bob')

    async def native_work(event, *_args, **_kwargs):
        # Synthetic executor, reached ONLY via real native admission/drain.
        seen.append((event.message_id, event.source.user_id, event.source.chat_id,
                     event.source.user_name, event.text, list(event.media_urls)))
        if event.message_id == 'heavy-1':
            heavy_started.set()
            await heavy_gate.wait()
        if event.media_urls:
            assert Path(event.media_urls[0]).read_text() == 'original-attachment'
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    heavy = MessageEvent(text='H' * 101, source=source, message_id='heavy-1')
    second = MessageEvent(text='followup', source=replace(source, user_id='bob', user_name='Bob'), message_id='same-2')
    short = MessageEvent(text='file', source=other, message_id='short-1', message_type=MessageType.DOCUMENT,
                         media_urls=[str(media)], media_types=['text/plain'])
    tasks = []
    try:
        tasks.append(asyncio.create_task(runner._handle_message(heavy)))
        await asyncio.wait_for(heavy_started.wait(), 8)
        tasks.append(asyncio.create_task(runner._handle_message(second)))
        assert await asyncio.wait_for(runner._handle_message(short), 8) == 'short-1'
        assert [x[0] for x in seen] == ['heavy-1', 'short-1']
        assert seen[1][1:4] == ('bob', 'independent', 'Bob')
        heavy_gate.set()
        assert await asyncio.wait_for(asyncio.gather(*tasks), 8) == ['heavy-1', 'same-2']
        assert [x[0] for x in seen] == ['heavy-1', 'short-1', 'same-2']
        assert seen[2][1:4] == ('bob', 'group', 'Bob')
        assert await runner._handle_message(heavy) is None
        assert [x[0] for x in seen].count('heavy-1') == 1
        rows = [r for sid in authority.sessions for r in list_session_admissions(authority.db, session_id=sid, pending_only=False)]
        assert len(rows) == 3 and all(r['status'] == 'terminal' for r in rows)
        assert all(r['outcome'] == 'completed' for r in rows)
    finally:
        heavy_gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(live.task for live in authority.sessions.values() if live.task), return_exceptions=True)
        authority.db.close()


@pytest.mark.asyncio
async def test_unauthorized_ingress_never_schedules(tmp_path, monkeypatch):
    runner, authority = await setup(tmp_path, monkeypatch)
    fired = []
    async def never(**kwargs):
        fired.append(1)
        return await kwargs['next_call']()
    get_plugin_manager()._middleware['gateway_turn_execution'].append(never)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='group', chat_type='group', user_id='mallory')
    try:
        assert await runner._handle_message(MessageEvent(text='hello', source=source, message_id='bad')) is None
        assert not fired and not authority.sessions
    finally:
        authority.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True], ids=['native-baseline', 'automatic-bounded'])
async def test_native_before_after_capacity_behavior(tmp_path, monkeypatch, enabled):
    runner, authority = await setup(tmp_path, monkeypatch)
    if not enabled:
        get_plugin_manager()._middleware['gateway_turn_execution'] = []
    gate, first, both = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []
    async def native_work(event, *_args, **_kwargs):
        seen.append(event.message_id)
        first.set()
        if len(seen) == 2:
            both.set()
        await gate.wait()
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    def event(i):
        return MessageEvent(text='short', message_id=f'cap-{i}', source=SessionSource(
            platform=Platform.TELEGRAM, chat_id=f'cap-chat-{i}', chat_type='dm', user_id='alice'))
    tasks = [asyncio.create_task(runner._handle_message(event(1)))]
    try:
        await asyncio.wait_for(first.wait(), 8)
        tasks.append(asyncio.create_task(runner._handle_message(event(2))))
        if enabled:
            from tests.waiting import async_wait_until
            await async_wait_until(lambda: len(authority.executing) == 2, timeout=8, what='two native claimed admissions')
            # Claim is before scheduling; second accepted/claimed work waits, not rejected.
            await asyncio.sleep(.01)
            assert seen == ['cap-1']
        else:
            await asyncio.wait_for(both.wait(), 8)
            assert seen == ['cap-1', 'cap-2']
        gate.set()
        assert await asyncio.wait_for(asyncio.gather(*tasks), 8) == ['cap-1', 'cap-2']
    finally:
        gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(live.task for live in authority.sessions.values() if live.task), return_exceptions=True)
        authority.db.close()


@pytest.mark.asyncio
async def test_synthetic_100_ordinary_requests_use_bounded_native_turns(tmp_path, monkeypatch):
    import json
    import time
    runner, authority = await setup(tmp_path, monkeypatch)
    seen, active, peak = [], 0, 0
    async def native_work(event, *_args, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.001)
            seen.append((event.message_id, event.source.chat_id, event.source.user_id))
            execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
            return event.message_id
        finally:
            active -= 1
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    start = time.monotonic()
    try:
        results = await asyncio.wait_for(asyncio.gather(*(runner._handle_message(MessageEvent(
            text='short synthetic request', message_id=f'm{i}', source=SessionSource(
                platform=Platform.TELEGRAM, chat_id=f'c{i}', chat_type='dm', user_id='alice')))
            for i in range(100))), 30)
        assert results == [f'm{i}' for i in range(100)]
        assert sorted(seen) == sorted((f'm{i}', f'c{i}', 'alice') for i in range(100))
        assert peak == 1
        report = {'scope': 'SYNTHETIC native ingress/SQLite/turn fixture, NOT model/platform/user capacity',
                  'requested': 100, 'unique_completed': len(set(results)), 'peak_synthetic_executor': peak,
                  'wall_seconds': time.monotonic() - start}
        (tmp_path / 'synthetic-100.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        await asyncio.gather(*(live.task for live in authority.sessions.values() if live.task), return_exceptions=True)
        authority.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['/status', '/stop', '/approve', '/deny', '/reset'])
async def test_controls_bypass_ordinary_turn_scheduler(tmp_path, monkeypatch, command):
    runner, authority = await setup(tmp_path, monkeypatch)
    fired = []
    async def broken(**kwargs):
        fired.append(1)
        raise RuntimeError('must not schedule control commands')
    get_plugin_manager()._middleware['gateway_turn_execution'] = [broken]
    try:
        reply = await runner._handle_message(MessageEvent(text=command, message_id='control', source=SessionSource(
            platform=Platform.TELEGRAM, chat_id='controls', chat_type='dm', user_id='alice')))
        assert not fired
        assert isinstance(reply, str) and reply
    finally:
        authority.db.close()


@pytest.mark.asyncio
async def test_policy_failure_is_terminal_failed_without_failopen(tmp_path, monkeypatch):
    runner, authority = await setup(tmp_path, monkeypatch)
    from hermes_state_runtime import get_session_admission
    seen = []
    async def broken(**kwargs):
        raise TimeoutError('synthetic policy failure before continuation')
    get_plugin_manager()._middleware['gateway_turn_execution'] = [broken]
    async def native_work(*args):
        seen.append(1)
    monkeypatch.setattr(runner, '_handle_message_with_agent', native_work)
    event = MessageEvent(text='ordinary request', message_id='failed-policy', source=SessionSource(
        platform=Platform.TELEGRAM, chat_id='policy', chat_type='dm', user_id='alice'))
    try:
        assert await runner._handle_message(event) == 'The admitted turn failed.'
        await asyncio.gather(*(live.task for live in authority.sessions.values() if live.task))
        rows = [r for sid in authority.sessions for r in list_session_admissions(authority.db, session_id=sid, pending_only=False)]
        assert len(rows) == 1 and rows[0]['status'] == 'terminal' and rows[0]['outcome'] == 'failed'
        assert await runner._handle_message(event) is None
        assert not seen
    finally:
        authority.db.close()
