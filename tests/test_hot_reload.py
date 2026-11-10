import asyncio
import sys
from types import ModuleType, SimpleNamespace

from hermes_for_teams.automatic import register_automatic


def test_reregistration_cannot_reset_live_capacity(monkeypatch,tmp_path):
    middleware = ModuleType('hermes_cli.middleware')
    monkeypatch.setattr(middleware, 'VALID_MIDDLEWARE', {'gateway_turn_execution'}, raising=False)
    cli = ModuleType('hermes_cli')
    gateway = ModuleType('gateway')
    seam = SimpleNamespace(COMPATIBILITY='legacy-1fd18277')
    monkeypatch.setattr(gateway, 'turn_scheduling', seam, raising=False)
    monkeypatch.setitem(sys.modules, 'hermes_cli', cli)
    monkeypatch.setitem(sys.modules, 'hermes_cli.middleware', middleware)
    monkeypatch.setitem(sys.modules, 'gateway', gateway)
    constants = ModuleType('hermes_constants')
    monkeypatch.setattr(constants,'get_hermes_home',lambda:tmp_path,raising=False)
    monkeypatch.setitem(sys.modules,'hermes_constants',constants)
    callbacks = []
    settings = {'automatic_enabled': True, 'automatic_interactive': 1}
    ctx = SimpleNamespace(get_config=lambda k, default=None: settings.get(k, default),
                          register_middleware=lambda kind, fn: callbacks.append(fn))
    async def case():
        gate, started, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def first():
            started.set()
            await gate.wait()
        async def second(): second_started.set()
        register_automatic(ctx)
        first_task = asyncio.create_task(callbacks[-1](next_call=first, profile_id='/same-profile'))
        await asyncio.wait_for(started.wait(),2)
        register_automatic(ctx)
        second_task = asyncio.create_task(callbacks[-1](next_call=second, profile_id='/same-profile'))
        try:
            await asyncio.sleep(.04)
            assert not second_started.is_set()
        finally:
            gate.set()
            await asyncio.gather(first_task, second_task)
        assert second_started.is_set()
    asyncio.run(case())
