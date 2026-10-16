import asyncio
from hermes_for_teams.automatic import AutomaticScheduler, logger


def test_logging_failure_does_not_change_execution_or_lease(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('test log handler failure')
    monkeypatch.setattr(logger, 'info', broken)
    async def case():
        scheduler = AutomaticScheduler()
        async def native():
            return 'native-result'
        assert await scheduler.run(next_call=native) == 'native-result'
        assert scheduler.active == {'interactive': 0, 'background': 0}
    asyncio.run(case())
