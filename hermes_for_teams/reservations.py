"""Durable capacity ledger. Unknown owners never expire into fresh capacity."""
import json
from pathlib import Path
import sqlite3
import uuid


class CapacityLedger:
    def __init__(self, path, limits):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS seats (id TEXT PRIMARY KEY, lane TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, limits TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            policy = db.execute('SELECT limits FROM policy WHERE id=1').fetchone()
            encoded = json.dumps(limits, sort_keys=True)
            if policy and policy[0] != encoded and db.execute('SELECT 1 FROM seats LIMIT 1').fetchone():
                raise RuntimeError('Drain native work before changing durable capacity')
            db.execute('INSERT OR REPLACE INTO policy VALUES (1,?)', (encoded,))

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def acquire(self, lane):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            policy = db.execute('SELECT limits FROM policy WHERE id=1').fetchone()
            if policy is None or json.loads(policy[0]) != self.limits:
                raise RuntimeError('Durable capacity policy changed; re-register before admission')
            count = db.execute('SELECT COUNT(*) FROM seats WHERE lane=?', (lane,)).fetchone()[0]
            if count >= self.limits[lane]:
                return None
            seat = uuid.uuid4().hex
            db.execute('INSERT INTO seats VALUES (?,?)', (seat, lane))
            return seat

    def release(self, seat):
        with self.connect() as db:
            db.execute('DELETE FROM seats WHERE id=?', (seat,))
