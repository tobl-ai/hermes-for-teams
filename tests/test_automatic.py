"""Offline scheduler tests. No provider or platform capacity claims."""
import asyncio
from contextvars import ContextVar

import pytest

from hermes_for_teams.automatic import AutomaticScheduler


def test_reserved_short_lane_and_fifo_context():
    async def case():
        scheduler = AutomaticScheduler(interactive=1, background=1, heavy_bytes=100)
        gate = asyncio.Event()
        started = asyncio.Event()
        seen = []
        scope = ContextVar('scope', default='wrong')
        async def heavy():
            started.set()
            await gate.wait()
            seen.append(('heavy', scope.get()))
        scope.set('original')
        h = asyncio.create_task(scheduler.run(input_bytes=101, next_call=heavy))
        await started.wait()
        async def short():
            seen.append(('short', scope.get()))
            return 'native-result'
        assert await asyncio.wait_for(scheduler.run(input_bytes=1, next_call=short), 1) == 'native-result'
        assert seen == [('short', 'original')]
        gate.set()
        await h
        assert scheduler.active == {'interactive': 0, 'background': 0}
    asyncio.run(case())


def test_cancel_does_not_release_physical_worker_or_replay():
    async def case():
        scheduler = AutomaticScheduler(interactive=1, background=1)
        gate, started = asyncio.Event(), asyncio.Event()
        calls = []
        async def physical():
            calls.append('one')
            started.set()
            await gate.wait()
        task = asyncio.create_task(scheduler.run(input_bytes=1, next_call=physical))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert scheduler.active['interactive'] == 1
        assert not task.done()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == ['one']
        assert scheduler.active['interactive'] == 0
    asyncio.run(case())


def test_synthetic_100_unique_bounded():
    async def case():
        scheduler = AutomaticScheduler(interactive=2, background=1)
        seen = []
        async def work(i):
            await asyncio.sleep(.001)
            seen.append(i)
            return i
        result = await asyncio.gather(*(scheduler.run(input_bytes=1, next_call=lambda i=i: work(i)) for i in range(100)))
        assert sorted(seen) == list(range(100)) == result
        assert scheduler.peak == {'interactive': 2, 'background': 0}
    asyncio.run(case())


def test_unknown_execution_holds_seat_without_replay():
    class Unknown(RuntimeError):
        pass
    async def case():
        scheduler = AutomaticScheduler(interactive=1, background=1, unknown_errors=(Unknown,))
        calls = []
        async def lost():
            calls.append(1)
            raise Unknown('lost native worker')
        with pytest.raises(Unknown):
            await scheduler.run(input_bytes=1, next_call=lost)
        queued = asyncio.create_task(scheduler.run(input_bytes=1, next_call=lost))
        await asyncio.sleep(.01)
        assert not queued.done()
        assert scheduler.active['interactive'] == 1
        assert scheduler.unknown['interactive'] == 1
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert calls == [1]
    asyncio.run(case())


def test_errors_propagate_no_retry():
    async def case():
        scheduler = AutomaticScheduler()
        calls = []
        async def work():
            calls.append(1)
            raise LookupError('native failure')
        with pytest.raises(LookupError):
            await scheduler.run(input_bytes=1, next_call=work)
        assert calls == [1]
        assert scheduler.active['interactive'] == 0
    asyncio.run(case())
