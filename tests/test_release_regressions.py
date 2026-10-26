import argparse
import json
import sys

import pytest

from hermes_for_teams.cli import dispatch, setup_parser
from hermes_for_teams.queue import Queue
from hermes_for_teams.worker import run_one, validate_hermes_result


def test_automatic_only_doctor_does_not_require_or_create_queue(capsys):
    parser = argparse.ArgumentParser()
    setup_parser(parser, embedded=True)
    args = parser.parse_args(['doctor'])
    assert dispatch(args, {'automatic_enabled': True}) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['automatic_scheduling_configured'] is True
    assert data['scope_configured'] is False
    assert data['runtime_verified'] is False


@pytest.mark.parametrize('lease', [0, -1, float('nan'), float('inf'), 86401, True])
def test_invalid_heartbeat_lease_cannot_disable_expiry(tmp_path, lease):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    q = Queue(directory / 'queue.db')
    job = q.submit('t', 'p', 'c', 'm', 'payload')
    owned = q.claim('background')
    with pytest.raises(ValueError):
        q.heartbeat('t', 'p', job['id'], owned['token'], lease=lease)
    assert q.get('t', 'p', job['id'])['expires'] == owned['expires']


def test_worker_accepts_terminal_result_after_large_progress_output(tmp_path):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    q = Queue(directory / 'queue.db')
    job = q.submit('t', 'p', 'c', 'm', 'payload')
    code = "import json; print('x'*80000); print(json.dumps({'type':'result','exit_code':0,'session_id':'s','text':'actual result'}))"
    assert run_one(q, 't', 'p', 'background', lambda job: [sys.executable, '-c', code],
                   timeout=10, result_validator=validate_hermes_result)
    assert q.get('t', 'p', job['id'])['state'] == 'succeeded'
    assert q.get('t', 'p', job['id'])['result'] == 'actual result'
