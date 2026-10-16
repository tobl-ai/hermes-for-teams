import argparse
import json
import os
import sys
import time
from pathlib import Path

import pytest

from hermes_for_teams.queue import Queue
from hermes_for_teams.worker import run_one, hermes_command, validate_hermes_result
from hermes_for_teams.plugin import register
from hermes_for_teams.adapters import workflow_request
from hermes_for_teams.cli import main


class Context:
    def __init__(self, settings):
        self.settings = settings
        self.tools = {}
        self.commands = {}
    def get_config(self, key, default=None):
        return self.settings.get(key, default)
    def register_tool(self, **kwargs):
        self.tools[kwargs['name']] = kwargs
    def register_cli_command(self, **kwargs):
        self.commands[kwargs['name']] = kwargs


def settings(tmp_path):
    return {'queue_path': str(tmp_path / 'private' / 'queue.db'), 'tenant': 'team', 'profile': 'tobl', 'enabled': True, 'trusted_operator_tools': True}


def test_plugin_scoped_tools_and_no_background_launch(tmp_path):
    ctx = Context(settings(tmp_path))
    register(ctx)
    assert set(ctx.tools) == {'teams_submit', 'teams_status', 'teams_cancel', 'teams_workflow'}
    assert 'teams' in ctx.commands
    submit = ctx.tools['teams_submit']['handler']
    a = json.loads(submit({'conversation': 'c', 'message': 'm', 'prompt': 'task'}))
    assert a['state'] == 'queued'
    denied = json.loads(submit({'conversation': 'c', 'message': 'other', 'prompt': 'task', 'profile': 'admin'}))
    assert 'error' in denied
    assert 'token' not in a and 'payload' not in a
    # No model-facing retry/resolve, profile, arbitrary shell, or state-path knob.
    for t in ctx.tools.values():
        props = t['schema']['parameters']['properties']
        assert not {'tenant', 'profile', 'queue_path', 'command', 'resolve'} & props.keys()


def test_shared_user_tools_fail_closed_without_trusted_operator_optin(tmp_path):
    cfg = settings(tmp_path)
    del cfg['trusted_operator_tools']
    ctx = Context(cfg)
    register(ctx)
    assert not any(tool['check_fn']() for tool in ctx.tools.values())
    result = json.loads(ctx.tools['teams_submit']['handler']({'conversation': 'forged', 'message': 'm', 'prompt': 'work'}))
    assert 'error' in result
    assert not Path(cfg['queue_path']).exists()


def test_disabled_plugin_opens_no_queue(tmp_path):
    cfg = settings(tmp_path)
    cfg['enabled'] = False
    ctx = Context(cfg)
    register(ctx)
    assert len(ctx.tools) == 4
    assert not any(tool['check_fn']() for tool in ctx.tools.values())
    result = json.loads(ctx.tools['teams_submit']['handler']({'conversation': 'c', 'message': 'm', 'prompt': 'task'}))
    assert 'error' in result
    assert not Path(cfg['queue_path']).exists()


def test_workflow_bridge_request_is_not_execution():
    r = workflow_request('Do research')
    assert r['action'] == 'run'
    assert r['graph']['nodes'][0]['goal'] == 'Do research'
    assert r['graph']['concurrency'] == 1
    assert not {'provider', 'model', 'profile'} & r['graph']['nodes'][0].keys()


def test_cli_help_status(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(['--help'])
    assert exc.value.code == 0
    cfg = tmp_path / 'settings.json'
    cfg.write_text(json.dumps(settings(tmp_path)))
    assert main(['--config', str(cfg), 'status']) == 0
    output = capsys.readouterr().out
    result = json.loads(output[output.rfind('\n{') + 1:])
    assert result['jobs'] == 0 and result['states'] == {}


def test_worker_success_timeout_and_failed_execution(tmp_path):
    q = Queue(tmp_path / 'private' / 'queue.db')
    q.submit('team', 'tobl', 'c', 'm', 'compute')
    # Test-only dependency injection: not a model-selectable production shell.
    assert run_one(q, 'team', 'tobl', 'background', lambda j: [sys.executable, '-c', 'print(sum(range(10000)))'], timeout=5)
    assert q.list('team', 'tobl')[0]['state'] == 'succeeded'
    assert q.list('team', 'tobl')[0]['result'].strip() == '49995000'
    q.submit('team', 'tobl', 'c', 'm2', 'slow')
    run_one(q, 'team', 'tobl', 'background', lambda j: [sys.executable, '-c', 'import time; time.sleep(5)'], timeout=.05)
    assert q.list('team', 'tobl')[1]['state'] == 'unknown'
    # Unknown holds the lane reservation and conversation until human reconciliation.
    q.resolve('team', 'tobl', q.list('team', 'tobl')[1]['id'], 'test process group has exited')
    q.submit('team', 'tobl', 'c', 'm3', 'fail')
    run_one(q, 'team', 'tobl', 'background', lambda j: [sys.executable, '-c', 'raise SystemExit(3)'], timeout=2)
    assert q.list('team', 'tobl')[2]['state'] == 'unknown'


def test_hermes_route_pinned_and_fail_closed(tmp_path):
    cfg = settings(tmp_path)
    with pytest.raises(ValueError):
        hermes_command(cfg, {'payload': 'test'})
    cfg.update(allow_cli_workers=True, hermes_executable='/usr/bin/false')
    argv = hermes_command(cfg, {'payload': 'test'})
    assert argv[:4] == ['/usr/bin/false', '--profile', 'tobl', 'chat']
    assert '--yolo' not in argv and '--provider' not in argv and '--model' not in argv
    assert argv[argv.index('--format') + 1] == 'stream-json'
    assert validate_hermes_result(json.dumps({'type': 'result', 'session_id': 's', 'exit_code': 0, 'text': 'done'})) == 'done'
    for bad in ('{"type":"admission","id":"queued"}', 'startup succeeded', '{"type":"result","exit_code":2,"text":"partial"}'):
        with pytest.raises(ValueError):
            validate_hermes_result(bad)
    with pytest.raises(ValueError):
        hermes_command(dict(cfg, profile='../admin'), {'payload': 'test'})
