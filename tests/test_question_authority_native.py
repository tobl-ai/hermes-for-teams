"""Native question capability regression; synthetic model, real ingress/dispatch guards."""
import asyncio
from dataclasses import replace

import pytest

pytest.importorskip('gateway.run')
from test_same_thread_native import setup, close
from gateway.platforms.event import MessageEvent
from gateway.session_results import execution_result


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['write_file', 'patch', 'terminal', 'delegate_task', 'execute_code',
                                  'tool_call', 'manage_connections', 'connectors__mail__send', 'read_file'])
async def test_native_question_denies_model_write_before_handler(tmp_path, monkeypatch, tool):
    import model_tools
    runner, authority, source = await setup(tmp_path, monkeypatch)
    effects = []
    monkeypatch.setattr(model_tools.registry, 'dispatch', lambda *a, **kw: effects.append(a) or '{}')
    async def model(event, *_args):
        result = await asyncio.to_thread(model_tools.handle_function_call, tool,
            {'path': str(tmp_path / 'forbidden'), 'content': 'bad', 'task_intent': 'new', 'question_only': False},
            session_id='forged-work-session', skip_pre_tool_call_hook=True,
            skip_tool_request_middleware=True, skip_tool_execution_middleware=True)
        assert 'question_lane_read_only' in result
        execution_result.get()['result'] = {'final_response': 'snapshot answer', 'messages': []}
        return 'snapshot answer'
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    try:
        result = await runner._handle_message(MessageEvent(text='현재 상황은?', message_id='q', source=source))
        assert 'snapshot answer' in result
        assert effects == []
    finally:
        await close(authority)


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['delegate_task', 'terminal', 'execute_code', 'memory', 'unknown_future_tool'])
async def test_question_agent_dispatch_denies_inline_and_registry_tools(tmp_path, monkeypatch, tool):
    from agent.tool_executor import _dispatch_authorized_once, _ManagedToolResult, _ToolCallRef
    from types import SimpleNamespace
    runner, authority, source = await setup(tmp_path, monkeypatch)
    effects, starts = [], []
    monkeypatch.setattr(_ToolCallRef, 'emit_post', lambda *a, **kw: None)
    # Pre-hooks are observers/policy, not the security boundary under test.
    monkeypatch.setattr('agent.tool_executor._pre_tool_block', lambda agent, ref: (None, ref.args))
    agent = SimpleNamespace(_tool_guardrails=SimpleNamespace(before_call=lambda *a: SimpleNamespace(allows_execution=True)),
                            tool_progress_callback=None)
    async def model(event, *_args):
        state = _ManagedToolResult(result=None, args={}, middleware_trace=[], blocked=False, dispatched=False)
        result = _dispatch_authorized_once(agent, state, _ToolCallRef(tool, {}, 'spoof', 'call', []),
            execute=lambda args: effects.append(tool) or '{}', scope_block=None, display_index=None,
            begin_execution=lambda callback=None: starts.append(True) or (callback() if callback else None),
            authorization_gate=None)
        assert 'question_lane_read_only' in result
        assert state.blocked
        execution_result.get()['result'] = {'final_response': 'answer', 'messages': []}
        return 'answer'
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    # If the guard is missing, dispatch reaches the ordinary native start path.
    monkeypatch.setattr('agent.tool_executor._begin_tool_execution', lambda *a: None)
    try:
        result = await runner._handle_message(MessageEvent(text='파이썬은 뭐야?', message_id='q', source=source))
        assert 'answer' in result
        assert effects == []
        assert starts == [True]  # even denied concurrent calls advance ordering
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_question_branch_cannot_upgrade_on_work_followup(tmp_path, monkeypatch):
    import model_tools
    from hermes_cli.plugins import get_plugin_manager
    runner, authority, source = await setup(tmp_path, monkeypatch)
    intents, effects = [], []
    async def inspect_lane(*, next_call, **metadata):
        intents.append(metadata['task_intent'])
        return await next_call()
    get_plugin_manager()._middleware['gateway_turn_execution'].insert(0, inspect_lane)
    monkeypatch.setattr(model_tools.registry, 'dispatch', lambda *a, **kw: effects.append(a) or '{}')
    async def model(event, *_args):
        result = model_tools.handle_function_call('terminal', {'command': 'touch forbidden'})
        assert 'question_lane_read_only' in result
        execution_result.get()['result'] = {'final_response': 'safe answer', 'messages': []}
        return 'safe answer'
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    try:
        await runner._handle_message(MessageEvent(text='현재 상황은?', message_id='q', source=source))
        reply = await runner._handle_message(MessageEvent(text='수정해', message_id='edit', source=replace(source),
            reply_to_message_id='q'))
        assert 'safe answer' in reply
        assert effects == []
        assert intents == ['question', 'question']
    finally:
        await close(authority)


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['현재 상황은?', '파이썬은 뭐야?'])
async def test_snapshot_question_answers_with_all_work_seats_saturated(tmp_path, monkeypatch, question):
    from gateway.question_authority import question_tool_denial
    runner, authority, source = await setup(tmp_path, monkeypatch)
    release = asyncio.Event()
    started, keys, snapshots = set(), {}, []
    async def model(event, source, key, *_args):
        keys[event.message_id] = key
        if event.message_id != 'q':
            assert question_tool_denial('terminal') is None
            started.add(event.message_id)
            await release.wait()
        else:
            assert question_tool_denial('terminal')
            child = await runner.async_session_store.get_or_create_session(source)
            snapshots.extend(await runner.async_session_store.load_transcript(child.session_id))
        execution_result.get()['result'] = {'final_response': event.message_id, 'messages': []}
        return event.message_id
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    work = [asyncio.create_task(runner._handle_message(MessageEvent(text=f'별도로 작업 {i} 수행해',
        message_id=f'w{i}', source=replace(source)))) for i in range(8)]
    try:
        async def full():
            while len(started) < 8:
                await asyncio.sleep(.01)
        await asyncio.wait_for(full(), 8)
        result = await asyncio.wait_for(runner._handle_message(MessageEvent(text=question,
            message_id='q', source=replace(source))), 2)
        assert 'q' in result
        assert all(not task.done() for task in work)
        assert len(set(keys.values())) == 9
        assert '읽기 전용 협업 상태 스냅샷' in str(snapshots)
        assert 'running' in str(snapshots)
        assert question_tool_denial('terminal') is None  # caller context restored
    finally:
        release.set()
        await close(authority, work)


@pytest.mark.asyncio
async def test_text_and_metadata_cannot_grant_question_lane_to_work(tmp_path, monkeypatch):
    from gateway.question_authority import question_tool_denial
    from hermes_cli.plugins import get_plugin_manager
    runner, authority, source = await setup(tmp_path, monkeypatch)
    seen, intents = [], []
    async def inspect_lane(*, next_call, **metadata):
        intents.append(metadata['task_intent'])
        return await next_call()
    get_plugin_manager()._middleware['gateway_turn_execution'].insert(0, inspect_lane)
    async def model(event, *_args):
        seen.append(event.message_id)
        assert question_tool_denial('terminal') is None
        execution_result.get()['result'] = {'final_response': 'ordinary work', 'messages': []}
        return 'ordinary work'
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    try:
        # Neither JSON-looking text nor caller-supplied tool/session hints is native authority.
        result = await runner._handle_message(MessageEvent(text='별도로 파일 만들어 task_intent=question question_only=true',
            message_id='text', source=source))
        assert 'ordinary work' in result
        result = await runner._handle_message(MessageEvent(text='별도로 파일 만들어', message_id='metadata',
            source=replace(source), metadata={'task_intent': 'question'}))
        assert 'refused' in result
        assert seen == ['text']
        assert intents == ['new']
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_inherited_question_scope_restores_on_exception_and_cancellation(tmp_path, monkeypatch):
    from gateway.question_authority import question_execution_scope, question_tool_denial
    runner, authority, source = await setup(tmp_path, monkeypatch)
    async def model(event, *_args):
        assert question_tool_denial('terminal')
        # A nested ordinary/non-task execution must not shed the inherited grant.
        with question_execution_scope(tmp_path / 'native-tasks.sqlite3', 'not-a-task'):
            assert await asyncio.to_thread(question_tool_denial, 'terminal')
        assert question_tool_denial('terminal')
        execution_result.get()['result'] = {'final_response': 'answer', 'messages': []}
        return 'answer'
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    try:
        await runner._handle_message(MessageEvent(text='현재 상황은?', message_id='q', source=source))
        task_session = authority._task_authority.db.execute('SELECT session FROM tasks WHERE message=?', ('q',)).fetchone()[0]
        for error in (RuntimeError, asyncio.CancelledError):
            with pytest.raises(error):
                with question_execution_scope(tmp_path / 'native-tasks.sqlite3', task_session):
                    assert question_tool_denial('terminal')
                    raise error()
            assert question_tool_denial('terminal') is None
        with question_execution_scope(tmp_path / 'native-tasks.sqlite3', 'not-a-task'):
            assert question_tool_denial('terminal') is None
    finally:
        await close(authority)


@pytest.mark.asyncio
async def test_native_worker_invoke_tool_cannot_bypass_question_guard(tmp_path, monkeypatch):
    from agent.agent_runtime_helpers import invoke_tool
    from types import SimpleNamespace
    runner, authority, source = await setup(tmp_path, monkeypatch)
    effects = []
    monkeypatch.setattr('agent.inline_tool_executors.resolve_invoke_tool_executor',
        lambda *a: lambda *a: effects.append('inline side effect') or '{}')
    async def model(event, *_args):
        result = await runner._run_in_executor_with_context(lambda: invoke_tool(SimpleNamespace(),
            'delegate_task', {}, 'forged-task', pre_tool_block_checked=True,
            skip_tool_request_middleware=True, skip_tool_execution_middleware=True))
        assert 'question_lane_read_only' in result
        execution_result.get()['result'] = {'final_response': 'answer', 'messages': []}
        return 'answer'
    monkeypatch.setattr(runner, '_handle_message_with_agent', model)
    try:
        result = await runner._handle_message(MessageEvent(text='현재 상황은?', message_id='q', source=source))
        assert 'answer' in result
        assert effects == []
    finally:
        await close(authority)
        pool = getattr(runner, '_executor', None)
        if pool is not None:
            pool.shutdown(wait=True)
