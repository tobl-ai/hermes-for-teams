"""Owner-local durable admission. No retry of a possibly executed job."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Conflict(ValueError):
    pass


BLOCKING = ('queued', 'running', 'cancel_requested', 'unknown')
OCCUPIED = ('running', 'cancel_requested', 'unknown')


class Queue:
    def __init__(self, path, capacities=None):
        if os.name != 'posix':
            raise ValueError('The explicit queue requires POSIX owner permissions; automatic scheduling is separate')
        self.path = Path(path).expanduser().absolute()
        if str(self.path.resolve()).startswith('/Volumes/'):
            raise ValueError('Live queue must be on private internal storage, not /Volumes')
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('Queue and immediate parent must not be symlinks')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private(self.path.parent, 0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self._private(self.path, 0o600)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS policy (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    tenant TEXT NOT NULL, profile TEXT NOT NULL, conversation TEXT NOT NULL,
                    message TEXT NOT NULL, payload TEXT NOT NULL, lane TEXT NOT NULL,
                    state TEXT NOT NULL, token TEXT, expires REAL, result TEXT, note TEXT,
                    UNIQUE(tenant,profile,message));
                CREATE INDEX IF NOT EXISTS scheduling ON jobs(state,lane,seq);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    conversation TEXT NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL);
            ''')
            caps = capacities or {'interactive': 2, 'background': 1}
            if set(caps) != {'interactive', 'background'} or any(type(v) is not int or not 1 <= v <= 32 for v in caps.values()):
                raise ValueError('Both lane capacities must be integers in 1..32')
            # The first owner creates policy. All workers read the same durable limits.
            db.execute('INSERT OR IGNORE INTO policy VALUES (?,?)', ('capacities', json.dumps(caps)))
            stored = json.loads(db.execute('SELECT value FROM policy WHERE key=?', ('capacities',)).fetchone()[0])
            if capacities is not None and capacities != stored:
                raise Conflict('Capacity policy mismatch; drain and create a new queue to change limits')
            self.capacities = stored

    @staticmethod
    def _private(path, mode):
        s = path.stat()
        if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != mode:
            raise PermissionError(f'Queue storage must be owner-only ({oct(mode)})')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA busy_timeout=30000')
            yield db
        finally:
            db.close()

    @contextmanager
    def _tx(self):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _event(db, job, kind):
        db.execute('INSERT INTO events(job_id,conversation,kind,at) VALUES(?,?,?,?)',
                   (job['id'], job['conversation'], kind, time.time()))

    @staticmethod
    def _get(db, tenant, profile, job_id):
        row = db.execute('SELECT * FROM jobs WHERE tenant=? AND profile=? AND id=?', (tenant, profile, job_id)).fetchone()
        if row is None:
            raise KeyError('Job not found in this scope')
        return dict(row)

    def submit(self, tenant, profile, conversation, message, payload, lane='background'):
        if lane not in self.capacities:
            raise ValueError('Invalid lane')
        for value in (tenant, profile, conversation, message):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError('Scope and identifiers must be nonempty strings of at most 256 chars')
        if not isinstance(payload, str) or not payload or len(payload.encode()) > 65536:
            raise ValueError('Payload must be 1..65536 bytes')
        with self._tx() as db:
            existing = db.execute('SELECT * FROM jobs WHERE tenant=? AND profile=? AND message=?', (tenant, profile, message)).fetchone()
            if existing:
                if (existing['conversation'], existing['payload'], existing['lane']) != (conversation, payload, lane):
                    raise Conflict('Idempotency key already has different input')
                return dict(existing)
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs(id,tenant,profile,conversation,message,payload,lane,state) VALUES(?,?,?,?,?,?,?,?)',
                       (job_id, tenant, profile, conversation, message, payload, lane, 'queued'))
            job = self._get(db, tenant, profile, job_id)
            self._event(db, job, 'queued')
            return job

    def _recover(self, db):
        for row in db.execute("SELECT * FROM jobs WHERE state IN ('running','cancel_requested') AND expires<?", (time.time(),)).fetchall():
            db.execute("UPDATE jobs SET state='unknown', note='Lease expired; execution may still exist' WHERE id=?", (row['id'],))
            self._event(db, row, 'unknown')

    def recover(self):
        with self._tx() as db:
            self._recover(db)

    def claim(self, lane, lease=60, scope=None):
        self._validate_lease(lease)
        if lane not in self.capacities:
            raise ValueError('Invalid lane or lease')
        with self._tx() as db:
            self._recover(db)
            occupied = db.execute("SELECT count(*) FROM jobs WHERE lane=? AND state IN ('running','cancel_requested','unknown')", (lane,)).fetchone()[0]
            if occupied >= self.capacities[lane]:
                return None
            params = [lane]
            scoped = ''
            if scope is not None:
                scoped = ' AND j.tenant=? AND j.profile=?'
                params.extend(scope)
            row = db.execute('''SELECT j.* FROM jobs j WHERE j.state='queued' AND j.lane=? ''' + scoped + '''
                AND NOT EXISTS (SELECT 1 FROM jobs earlier WHERE earlier.tenant=j.tenant
                AND earlier.profile=j.profile AND earlier.conversation=j.conversation AND earlier.seq<j.seq
                AND earlier.state IN ('queued','running','cancel_requested','unknown')) ORDER BY j.seq LIMIT 1''', params).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',token=?,expires=? WHERE id=?", (token, time.time() + lease, row['id']))
            self._event(db, row, 'claimed')
            return self._get(db, row['tenant'], row['profile'], row['id'])

    def get(self, tenant, profile, job_id):
        with self._db() as db:
            return self._get(db, tenant, profile, job_id)

    def list(self, tenant, profile):
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM jobs WHERE tenant=? AND profile=? ORDER BY seq', (tenant, profile))]

    def heartbeat(self, tenant, profile, job_id, token, lease=60):
        self._validate_lease(lease)
        with self._tx() as db:
            self._recover(db)
            j = self._get(db, tenant, profile, job_id)
            if j['token'] != token or j['state'] not in ('running', 'cancel_requested'):
                raise Conflict('Worker no longer owns a live lease')
            db.execute('UPDATE jobs SET expires=? WHERE id=?', (time.time() + lease, job_id))
            return j['state']

    @staticmethod
    def _validate_lease(lease):
        if type(lease) not in (int, float) or not math.isfinite(lease) or not 0 < lease <= 86400:
            raise ValueError('Lease must be a finite number in (0,86400]')

    def finish(self, tenant, profile, job_id, token, result, uncertain=False):
        with self._tx() as db:
            self._recover(db)
            j = self._get(db, tenant, profile, job_id)
            if j['token'] != token or j['state'] not in ('running', 'cancel_requested'):
                raise Conflict('Stale worker cannot commit')
            state = 'unknown' if uncertain or j['state'] == 'cancel_requested' else 'succeeded'
            db.execute('UPDATE jobs SET state=?, result=? WHERE id=?', (state, result, job_id))
            self._event(db, j, state)

    def cancel(self, tenant, profile, job_id):
        with self._tx() as db:
            j = self._get(db, tenant, profile, job_id)
            state = {'queued': 'cancelled', 'running': 'cancel_requested'}.get(j['state'])
            if state:
                db.execute('UPDATE jobs SET state=? WHERE id=?', (state, job_id))
                self._event(db, j, state)
            return self._get(db, tenant, profile, job_id)

    def resolve(self, tenant, profile, job_id, note):
        if not isinstance(note, str) or not note.strip():
            raise ValueError('An operator reconciliation note is required')
        with self._tx() as db:
            j = self._get(db, tenant, profile, job_id)
            if j['state'] != 'unknown':
                raise Conflict('Only unknown work can be reconciled')
            db.execute("UPDATE jobs SET state='resolved', note=? WHERE id=?", (note, job_id))
            self._event(db, j, 'resolved')

    def events(self):
        """Operator-only diagnostic census, never exposed as a model tool."""
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')]
