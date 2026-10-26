import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_for_teams.automatic import register_automatic

gateway = pytest.importorskip('gateway')

pytestmark = pytest.mark.skipif(
    (Path(gateway.__file__).parent / 'session_finite.py').exists(),
    reason='requires verified legacy source tree',
)

@pytest.mark.parametrize('mode', ['fail_before', 'fabricate', 'ack_lost', 'double', 'swallow_native'])
def test_legacy_seam_preserves_native_result_and_fail_closed(monkeypatch, mode):
    from gateway.turn_scheduling import run_scheduled_turn
    from hermes_cli import plugins
    calls = []
    async def native():
        calls.append(1)
        if mode == 'swallow_native': raise LookupError('native')
        return 'actual'
    async def policy(next_call, **kwargs):
        if mode == 'fail_before': raise TimeoutError('policy')
        if mode == 'fabricate': return 'invented'
        if mode == 'swallow_native':
            try: await next_call()
            except LookupError: return 'invented'
        value = await next_call()
        if mode == 'double':
            with pytest.raises(RuntimeError): await next_call()
        if mode == 'ack_lost': raise TimeoutError('ack')
        return value
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: SimpleNamespace(_middleware={
        'gateway_turn_execution': [policy]}))
    async def case():
        if mode == 'fail_before':
            with pytest.raises(TimeoutError): await run_scheduled_turn(native)
        elif mode == 'fabricate':
            with pytest.raises(RuntimeError): await run_scheduled_turn(native)
        elif mode == 'swallow_native':
            with pytest.raises(LookupError): await run_scheduled_turn(native)
        else:
            assert await run_scheduled_turn(native) == 'actual'
        assert len(calls) == (0 if mode in ['fail_before', 'fabricate'] else 1)
    asyncio.run(case())


def test_unknown_layout_without_managed_worker_still_refused(monkeypatch):
    from gateway import turn_scheduling
    from hermes_cli import middleware
    monkeypatch.setattr(middleware, 'VALID_MIDDLEWARE', {'gateway_turn_execution'})
    monkeypatch.setattr(turn_scheduling, 'COMPATIBILITY', 'unknown')
    monkeypatch.setitem(sys.modules, 'gateway.session_managed_worker', None)
    ctx = SimpleNamespace(get_config=lambda k, default=None: True if k == 'automatic_enabled' else default,
                          register_middleware=lambda *a: pytest.fail('unsupported registration'))
    with pytest.raises(ModuleNotFoundError): register_automatic(ctx)
