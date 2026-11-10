import asyncio
import pytest
from hermes_for_teams.automatic import AutomaticScheduler
from hermes_for_teams.reservations import CapacityLedger


def test_stale_policy_instance_cannot_overbook(tmp_path):
    path = tmp_path / 'seats.db'
    old = CapacityLedger(path, {'interactive': 3})
    new = CapacityLedger(path, {'interactive': 1})
    assert new.acquire('interactive') is not None
    with pytest.raises(RuntimeError, match='policy'):
        old.acquire('interactive')


@pytest.mark.asyncio
async def test_unknown_seat_survives_scheduler_recreation(tmp_path):
    class Unknown(RuntimeError):
        pass
    async def uncertain():
        raise Unknown()
    first = AutomaticScheduler(1, 1, durable_path=tmp_path / 'seats.db', unknown_errors=(Unknown,))
    with pytest.raises(Unknown):
        await first.run(next_call=uncertain)
    second = AutomaticScheduler(1, 1, durable_path=tmp_path / 'seats.db')
    entered = []
    async def work():
        entered.append(True)
    task = asyncio.create_task(second.run(next_call=work))
    try:
        await asyncio.sleep(.1)
        assert not entered and not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_question_has_bounded_reserve_when_work_seats_full():
    scheduler = AutomaticScheduler(1, 1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def coding():
        entered.set()
        await release.wait()
    async def question():
        return 'status'
    task = asyncio.create_task(scheduler.run(next_call=coding))
    try:
        await entered.wait()
        assert await asyncio.wait_for(scheduler.run(next_call=question, task_intent='question'), .2) == 'status'
        assert not task.done()
    finally:
        release.set()
        await task
