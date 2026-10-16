"""Opt-in ordinary native-turn scheduling, not a prompt reinjection queue.

Per registration/event-loop capacity. Native authority keeps durable FIFO, identity,
media, approvals and delivery. Classification is a size heuristic, not predicted cost.
"""
import asyncio
import logging
from weakref import WeakKeyDictionary

logger = logging.getLogger('hermes.teams.scheduler')


def _log(message, *args):
    try:
        logger.info(message, *args)
    except Exception:
        pass  # Operational logging must not change execution or leak a seat.



async def _join_physical(task):
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.done() and task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


class AutomaticScheduler:
    def __init__(self, interactive=2, background=1, heavy_bytes=4096, *, unknown_errors=()):
        for value in (interactive, background, heavy_bytes):
            if type(value) is not int or value < 1:
                raise ValueError('automatic scheduler limits must be positive integers')
        self.heavy_bytes = heavy_bytes
        self._seats = {'interactive': asyncio.Semaphore(interactive),
                       'background': asyncio.Semaphore(background)}
        self.active = dict.fromkeys(self._seats, 0)
        self.peak = dict.fromkeys(self._seats, 0)
        self.unknown = dict.fromkeys(self._seats, 0)
        self._unknown_errors = unknown_errors

    async def run(self, *, next_call, input_bytes=0, physical_completion=None, **metadata):
        lane = 'background' if input_bytes >= self.heavy_bytes else 'interactive'
        # Waiting cancellation creates no work. Native unknown workers retain
        # reservations; there is intentionally no automatic release/replay.
        await self._seats[lane].acquire()
        self.active[lane] += 1
        self.peak[lane] = max(self.peak[lane], self.active[lane])
        _log('teams_auto enter lane=%s active=%d', lane, self.active[lane])
        unknown = False
        try:
            return await _join_physical(asyncio.create_task(next_call()))
        except self._unknown_errors:
            unknown = True
            self.unknown[lane] += 1
            raise
        finally:
            if not unknown:
                def release(completed=None):
                    if completed is not None and completed.cancelled():
                        self.unknown[lane] += 1
                        return
                    self.active[lane] -= 1
                    self._seats[lane].release()
                    _log('teams_auto leave lane=%s active=%d', lane, self.active[lane])
                if physical_completion is not None and not physical_completion.done():
                    # Return the native timeout/reply promptly, but retain the seat
                    # until the real executor's worker_done signal arrives.
                    physical_completion.add_done_callback(release)
                else:
                    release(physical_completion)


def register_automatic(ctx):
    if ctx.get_config('automatic_enabled', False) is not True:
        return
    # Refuse unsupported hosts rather than registering an inert unknown kind.
    from hermes_cli.middleware import VALID_MIDDLEWARE
    if 'gateway_turn_execution' not in VALID_MIDDLEWARE:
        raise RuntimeError('automatic scheduling requires optional gateway_turn_execution core seam')
    limits = (ctx.get_config('automatic_interactive', 2),
              ctx.get_config('automatic_background', 1),
              ctx.get_config('automatic_heavy_bytes', 4096))
    from gateway.session_managed_worker import ManagedExecutionUnknown
    unknown_errors = (ManagedExecutionUnknown,)
    AutomaticScheduler(*limits, unknown_errors=unknown_errors)  # validate before registration
    schedulers = WeakKeyDictionary()

    async def schedule(**kwargs):
        loop = asyncio.get_running_loop()
        if loop not in schedulers:
            schedulers[loop] = AutomaticScheduler(*limits, unknown_errors=unknown_errors)
        return await schedulers[loop].run(**kwargs)
    ctx.register_middleware('gateway_turn_execution', schedule)
