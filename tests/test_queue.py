import multiprocessing as mp
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from hermes_for_teams.queue import Queue, Conflict


def drain(path):
    q = Queue(path, {'interactive': 2, 'background': 2})
    while True:
        job = q.claim('background', lease=5)
        if not job:
            return
        # Real CPU computation, not provider inference.
        result = sum(i * i for i in range(1000))
        time.sleep(.005)
        q.finish(job['tenant'], job['profile'], job['id'], job['token'], str(result))


@pytest.fixture
def q(tmp_path):
    return Queue(tmp_path / 'private' / 'queue.db', {'interactive': 2, 'background': 2})


def put(q, message='m', conversation='c', lane='background', tenant='t', profile='p', payload='hello'):
    return q.submit(tenant, profile, conversation, message, payload, lane)


def test_dedup_and_conflict(q):
    a = put(q)
    assert put(q)['id'] == a['id']
    with pytest.raises(Conflict):
        put(q, payload='changed')
    with ThreadPoolExecutor(10) as pool:
        ids = list(pool.map(lambda _: put(q, message='race')['id'], range(30)))
    assert len(set(ids)) == 1


def test_fifo_across_lanes_and_reserved_capacity(q):
    a = put(q, 'a', 'same')
    put(q, 'b', 'same', 'interactive')
    put(q, 'c', 'other')
    put(q, 'd', 'third')
    put(q, 'e', 'chat', 'interactive')
    first = q.claim('background')
    second = q.claim('background')
    assert first['id'] == a['id']
    assert second is not None
    assert q.claim('background') is None
    chat = q.claim('interactive')
    assert chat['conversation'] == 'chat'
    assert q.claim('interactive') is None
    q.finish('t', 'p', first['id'], first['token'], 'ok')
    assert q.claim('interactive')['conversation'] == 'same'


def test_crash_unknown_never_replayed_or_overtaken(q):
    a = put(q, 'a')
    put(q, 'b')
    first = q.claim('background', lease=.01)
    time.sleep(.03)
    q.recover()
    assert q.get('t', 'p', a['id'])['state'] == 'unknown'
    assert q.claim('background') is None
    with pytest.raises(Conflict):
        q.finish('t', 'p', a['id'], first['token'], 'late')
    q.resolve('t', 'p', a['id'], 'operator confirmed no replay')
    assert q.claim('background') is not None


def test_cancel_and_scope(q):
    a = put(q)
    with pytest.raises(KeyError):
        q.get('other', 'p', a['id'])
    with pytest.raises(KeyError):
        q.cancel('other', 'p', a['id'])
    q.cancel('t', 'p', a['id'])
    assert q.get('t', 'p', a['id'])['state'] == 'cancelled'
    b = put(q, 'b')
    running = q.claim('background')
    q.cancel('t', 'p', b['id'])
    assert q.get('t', 'p', b['id'])['state'] == 'cancel_requested'
    q.finish('t', 'p', b['id'], running['token'], 'may have written')
    assert q.get('t', 'p', b['id'])['state'] == 'unknown'
    assert q.claim('background') is None


def test_owner_only(q):
    assert q.path.stat().st_mode & 0o777 == 0o600
    assert q.path.parent.stat().st_mode & 0o777 == 0o700


def test_100_jobs_multiprocess(q):
    for i in range(100):
        put(q, str(i), str(i // 4))
    ctx = mp.get_context('spawn')
    processes = [ctx.Process(target=drain, args=(str(q.path),)) for _ in range(5)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(30)
        assert p.exitcode == 0
    rows = q.list('t', 'p')
    assert len(rows) == 100
    assert all(j['state'] == 'succeeded' and j['result'] == '332833500' for j in rows)
    events = q.events()
    active = 0
    maximum = 0
    for event in events:
        if event['kind'] == 'claimed':
            active += 1
        elif event['kind'] == 'succeeded':
            active -= 1
        maximum = max(maximum, active)
    assert active == 0 and maximum <= 2 and maximum > 0
    # Per-conversation event order is submission order even across processes.
    for c in range(25):
        claimed = [e['job_id'] for e in events if e['kind'] == 'claimed' and e['conversation'] == str(c)]
        expected = [j['id'] for j in rows if j['conversation'] == str(c)]
        assert claimed == expected
