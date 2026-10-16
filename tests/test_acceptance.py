"""Additional adversarial and process-boundary acceptance cases."""
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from hermes_for_teams.queue import Queue, Conflict
from hermes_for_teams.worker import run_one


def submit_batch(path, batch):
    q = Queue(path)
    for i in range(batch * 20, (batch + 1) * 20):
        q.submit('t', 'p', str(i), str(i), 'compute')
        q.submit('t', 'p', str(i), str(i), 'compute')


def crash_claim(path):
    q = Queue(path)
    assert q.claim('background', lease=.1)
    os._exit(7)


def test_100_concurrent_process_submissions_and_dedup(tmp_path):
    q = Queue(tmp_path / 'private' / 'queue.db')
    ctx = mp.get_context('spawn')
    ps = [ctx.Process(target=submit_batch, args=(str(q.path), i)) for i in range(5)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(20)
        assert p.exitcode == 0
    assert len(q.list('t', 'p')) == 100
    assert len(q.events()) == 100


def test_real_process_crash_does_not_replay(tmp_path):
    q = Queue(tmp_path / 'private' / 'queue.db')
    j = q.submit('t', 'p', 'c', 'm', 'compute')
    p = mp.get_context('spawn').Process(target=crash_claim, args=(str(q.path),))
    p.start()
    p.join(10)
    assert p.exitcode == 7
    time.sleep(.15)
    q.recover()
    assert q.get('t', 'p', j['id'])['state'] == 'unknown'
    q.submit('t', 'p', 'different', 'm2', 'compute')
    # Unknown work retains the background slot: an orphan could still be alive.
    assert q.claim('background') is None


def test_long_worker_does_not_block_reserved_chat_lane(tmp_path):
    q = Queue(tmp_path / 'private' / 'queue.db')
    bg = q.submit('t', 'p', 'long-conversation', 'long', 'long')
    chat = q.submit('t', 'p', 'chat-conversation', 'chat', 'short', 'interactive')
    with ThreadPoolExecutor(2) as pool:
        background = pool.submit(run_one, q, 't', 'p', 'background',
                                 lambda j: [sys.executable, '-c', 'import time; time.sleep(1); print("long done")'])
        deadline = time.monotonic() + 5
        while q.get('t', 'p', bg['id'])['state'] != 'running':
            assert time.monotonic() < deadline
            time.sleep(.01)
        run_one(q, 't', 'p', 'interactive', lambda j: [sys.executable, '-c', 'print(sum(range(10000)))'])
        assert q.get('t', 'p', chat['id'])['state'] == 'succeeded'
        assert q.get('t', 'p', bg['id'])['state'] == 'running'
        assert background.result(timeout=5)


def test_running_cancel_and_scope_cannot_be_stolen(tmp_path):
    q = Queue(tmp_path / 'private' / 'queue.db')
    job = q.submit('t', 'p', 'c', 'm', 'work')
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(run_one, q, 't', 'p', 'background',
                             lambda j: [sys.executable, '-c', 'import time; time.sleep(5)'])
        deadline = time.monotonic() + 5
        while q.get('t', 'p', job['id'])['state'] != 'running':
            assert time.monotonic() < deadline
            time.sleep(.01)
        with pytest.raises(KeyError):
            q.cancel('evil', 'p', job['id'])
        q.cancel('t', 'p', job['id'])
        assert future.result(timeout=5)
    assert q.get('t', 'p', job['id'])['state'] == 'unknown'
    assert not q.claim('background')


def test_policy_and_storage_boundaries(tmp_path):
    q = Queue(tmp_path / 'private' / 'queue.db')
    with pytest.raises(Conflict):
        Queue(q.path, {'interactive': 32, 'background': 32})
    with pytest.raises(ValueError):
        Queue('/Volumes/unsafe/queue.db')
    link = tmp_path / 'link.db'
    link.symlink_to(q.path)
    with pytest.raises(ValueError):
        Queue(link)
    public = tmp_path / 'public'
    public.mkdir(mode=0o755)
    with pytest.raises(PermissionError):
        Queue(public / 'queue.db')
    q.submit('t', 'p', 'c', 'm', 'work')
    assert q.claim('background', scope=('other', 'p')) is None
    owned = q.claim('background', scope=('t', 'p'))
    with pytest.raises(Conflict):
        q.finish('t', 'p', owned['id'], 'forged-token', 'forged')
