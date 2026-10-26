"""Operator CLI. No worker process starts on plugin load."""
import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

from .adapters import workflow_request
from .plugin import public_job
from .queue import Queue
from .worker import hermes_command, run_one, validate_hermes_result


def setup_parser(parser, embedded=False):
    if not embedded:
        parser.add_argument('--config', required=True, help='Operator JSON settings, never model input')
    subs = parser.add_subparsers(dest='teams_action', required=True)
    subs.add_parser('status')
    submit = subs.add_parser('submit')
    submit.add_argument('--conversation', required=True)
    submit.add_argument('--message', required=True)
    submit.add_argument('--prompt', required=True)
    submit.add_argument('--lane', choices=['interactive', 'background'], default='background')
    for name in ('get', 'cancel'):
        subs.add_parser(name).add_argument('job_id')
    resolve = subs.add_parser('resolve')
    resolve.add_argument('job_id')
    resolve.add_argument('--note', required=True, help='Confirm worker stopped and external effects reconciled')
    subs.add_parser('recover')
    worker = subs.add_parser('worker')
    worker.add_argument('--lane', choices=['interactive', 'background'], required=True)
    worker.add_argument('--timeout', type=float, default=300)
    worker.add_argument('--watch', action='store_true', help='Remain polling until operator stops process')
    subs.add_parser('doctor')
    subs.add_parser('workflow').add_argument('--prompt', required=True)


def dispatch(args, cfg):
    action = args.teams_action
    if action == 'workflow':
        print(json.dumps(workflow_request(args.prompt), ensure_ascii=False))
        return 0
    if action == 'doctor':
        checks = {'scope_configured': all(isinstance(cfg.get(k), str) and cfg[k].strip()
                                         for k in ('queue_path', 'tenant', 'profile')),
                  'automatic_chat_offload': False,
                  'automatic_scheduling_configured': cfg.get('automatic_enabled') is True,
                  'runtime_verified': False,
                  'operator_worker_supported': os.name == 'posix',
                  'cli_worker_opt_in': cfg.get('allow_cli_workers') is True,
                  'provider_capacity_verified': False,
                  'per_user_authorization': False,
                  'model_tools_trusted_operator_only': cfg.get('trusted_operator_tools') is True}
        if checks['cli_worker_opt_in']:
            hermes_command(cfg, {'payload': 'route validation only; never executed'})
        print(json.dumps(checks))
        return 0
    if not all(isinstance(cfg.get(k), str) and cfg[k].strip() for k in ('queue_path', 'tenant', 'profile')):
        raise ValueError('Configure queue_path, tenant, profile explicitly')
    q = Queue(cfg['queue_path'])
    scope = (cfg['tenant'], cfg['profile'])
    if action == 'status':
        rows = q.list(*scope)
        result = {'jobs': len(rows), 'states': dict(Counter(j['state'] for j in rows)), 'capacities': q.capacities}
    elif action == 'submit':
        result = public_job(q.submit(*scope, args.conversation, args.message, args.prompt, args.lane))
    elif action == 'get':
        result = public_job(q.get(*scope, args.job_id))
    elif action == 'cancel':
        result = public_job(q.cancel(*scope, args.job_id))
    elif action == 'resolve':
        q.resolve(*scope, args.job_id, args.note)
        result = public_job(q.get(*scope, args.job_id))
    elif action == 'recover':
        q.recover()
        result = {'recovered': True, 'replayed': False}
    elif action == 'worker':
        hermes_command(cfg, {'payload': 'validate before claiming'})
        count = 0
        try:
            while True:
                worked = run_one(q, *scope, args.lane, lambda job: hermes_command(cfg, job), timeout=args.timeout, result_validator=validate_hermes_result)
                if worked:
                    count += 1
                elif not args.watch:
                    break
                else:
                    time.sleep(.5)
        except KeyboardInterrupt:
            pass
        result = {'executed_attempts': count}
    else:
        raise ValueError('Unknown action')
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hermes-teams')
    setup_parser(parser)
    args = parser.parse_args(argv)
    try:
        cfg = json.loads(Path(args.config).read_text())
        return dispatch(args, cfg)
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
