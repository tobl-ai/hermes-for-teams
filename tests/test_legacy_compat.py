"""Run with scripts/verify_automatic.py --core <patched 1fd18277 checkout>."""
import asyncio
import importlib
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from hermes_for_teams.automatic import AutomaticScheduler, register_automatic

gateway = pytest.importorskip('gateway')

pytestmark = pytest.mark.skipif(
    (Path(gateway.__file__).parent / 'session_finite.py').exists(),
    reason='legacy integration requires the actual 1fd18277 source tree',
)

def test_legacy_registration_without_managed_worker(monkeypatch):
    from hermes_cli import middleware
    monkeypatch.setattr(middleware, 'VALID_MIDDLEWARE', {'gateway_turn_execution'})
    seam = importlib.import_module('gateway.turn_scheduling')
    assert seam.COMPATIBILITY == 'legacy-1fd18277'
    assert Path(seam.__file__).parent == Path(gateway.__file__).parent
    monkeypatch.setitem(sys.modules, 'gateway.session_managed_worker', None)
    registered = []
    ctx = SimpleNamespace(get_config=lambda k, default=None: True if k == 'automatic_enabled' else default,
                          register_middleware=lambda k, fn: registered.append((k, fn)))
    register_automatic(ctx)
    assert registered[0][0] == 'gateway_turn_execution'


def test_real_legacy_wrapper_and_executor_hold_physical_capacity(monkeypatch):
    from gateway.run_turn import GatewayTurnMixin
    from hermes_cli import plugins
    scheduler = AutomaticScheduler(interactive=1)
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: SimpleNamespace(_middleware={
        'gateway_turn_execution': [scheduler.run]}))
    fake_run = ModuleType('gateway.run')
    fake_run._float_env = lambda name, default: 0
    fake_run._watch_gateway_turn_inactivity = lambda **kw: None
    monkeypatch.setitem(sys.modules, 'gateway.run', fake_run)
    fake_registry = ModuleType('tools.process_registry')
    fake_registry.process_registry = SimpleNamespace(snapshot_running_ids=lambda key: frozenset())
    monkeypatch.setitem(sys.modules, 'tools.process_registry', fake_registry)
    started, release = threading.Event(), threading.Event()
    result = {'native': 'unchanged'}
    calls = []

    class Runner(GatewayTurnMixin):
        _RunAgentWorker = SimpleNamespace
        def _profile_scope_for_source(self, source):
            return nullcontext()
        async def _run_in_executor_with_context(self, fn):
            return await asyncio.to_thread(fn)
        async def _run_agent_inner(self, message, context_prompt, history, source, session_id, **kw):
            calls.append((message, context_prompt, history, source, session_id, kw))
            if message == 'first':
                ctx = SimpleNamespace(agent_holder=[None], session_key='s', run_generation=None, session_id='s')
                def work():
                    started.set()
                    release.wait(5)
                self.worker = self._run_agent_start_turn_worker(ctx, work)
                while not started.is_set(): await asyncio.sleep(.005)
                return result  # Native inactivity response returns before its real thread.
            return result

    async def case():
        runner, source, history = Runner(), object(), []
        second = None
        try:
            assert await runner._run_agent('first', 'context', history, source, 's', marker=history) is result
            assert scheduler.active['interactive'] == 1
            second = asyncio.create_task(runner._run_agent('second', 'context', history, source, 's2'))
            await asyncio.sleep(.08)
            assert len(calls) == 1
            assert not second.done()
            release.set()
            assert await asyncio.wait_for(second, 2) is result
            assert calls[0][2] is history and calls[0][3] is source and calls[0][5]['marker'] is history
            await runner.worker.executor_task
            assert scheduler.active['interactive'] == 0
        finally:
            release.set()
            if second is not None: await second
    asyncio.run(case())


def test_recursive_native_followup_does_not_deadlock_one_slot(monkeypatch):
    from gateway.run_turn import GatewayTurnMixin
    from hermes_cli import plugins
    scheduler = AutomaticScheduler(interactive=1)
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: SimpleNamespace(_middleware={
        'gateway_turn_execution': [scheduler.run]}))
    class Runner(GatewayTurnMixin):
        def _profile_scope_for_source(self, source): return nullcontext()
        async def _run_agent_inner(self, message, context_prompt, history, source, session_id, **kw):
            if message == 'outer':
                return await self._run_agent('followup', context_prompt, history, source, session_id)
            return 'native-followup'
    async def case():
        assert await asyncio.wait_for(Runner()._run_agent('outer', '', [], object(), 's'), 2) == 'native-followup'
        assert scheduler.peak['interactive'] == 1
        assert scheduler.active['interactive'] == 0
    asyncio.run(case())
