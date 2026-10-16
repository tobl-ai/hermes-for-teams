import asyncio
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip('gateway.turn_scheduling')
from gateway.turn_scheduling import run_scheduled_turn, KIND
from hermes_for_teams.automatic import AutomaticScheduler


@pytest.mark.asyncio
async def test_native_timeout_keeps_seat_until_actual_executor_done(monkeypatch):
    from hermes_cli import plugins
    from gateway import session_runtime_workers as workers
    scheduler = AutomaticScheduler(interactive=1, background=1)
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: SimpleNamespace(_middleware={KIND: [scheduler.run]}))
    monkeypatch.setattr(workers, 'track_turn_worker', lambda *args: None)
    release = threading.Event()
    started = threading.Event()
    worker = SimpleNamespace(worker_done=threading.Event())
    def physical_work():
        started.set()
        try:
            release.wait(5)
        finally:
            worker.worker_done.set()
    class Runner:
        async def _run_in_executor_with_context(self, fn):
            return await asyncio.to_thread(fn)
    async def detached_native():
        workers.start_turn_worker(Runner(), worker, [], physical_work)
        while not started.is_set():
            await asyncio.sleep(.001)
        return {'failed': True, 'error': 'timeout'}
    second_started = asyncio.Event()
    async def second():
        second_started.set()
        return 'second'
    task = None
    try:
        result = await run_scheduled_turn(detached_native, input_bytes=0)
        assert result['error'] == 'timeout'  # user receives timeout without waiting for the orphan
        assert not worker.worker_done.is_set()
        assert scheduler.active['interactive'] == 1
        task = asyncio.create_task(run_scheduled_turn(second, input_bytes=0))
        await asyncio.sleep(.02)
        assert not second_started.is_set()
        release.set()
        await worker.executor_task
        assert await asyncio.wait_for(task, 2) == 'second'
        assert scheduler.active['interactive'] == 0
    finally:
        release.set()
        if getattr(worker, 'executor_task', None):
            await worker.executor_task
        if task:
            await asyncio.gather(task, return_exceptions=True)
