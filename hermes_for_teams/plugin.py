"""Native PluginContext registration. No core imports or monkeypatching."""
import json

from .adapters import workflow_request
from .queue import Queue


def public_job(job):
    return {k: job[k] for k in ('id', 'conversation', 'message', 'lane', 'state', 'result', 'note')}


def register(ctx):
    # Registration is cheap and creates no DB, worker, hook, or inference request.
    from .automatic import register_automatic
    register_automatic(ctx)
    def setup(parser):
        from .cli import setup_parser
        setup_parser(parser, embedded=True)

    def cli_handler(args):
        from .cli import dispatch
        return dispatch(args, read_settings())

    def read_settings():
        return {key: ctx.get_config(key, default) for key, default in (
            ('enabled', False), ('trusted_operator_tools', False), ('tenant', None), ('profile', None), ('queue_path', None),
            ('allow_cli_workers', False), ('hermes_executable', None),
            ('existing_owner_control_home', None), ('existing_owner_profile_home', None))}

    ctx.register_cli_command(name='teams', help='Explicit durable team queue', setup_fn=setup, handler_fn=cli_handler)
    def tools_allowed():
        return ctx.get_config('enabled', False) is True and ctx.get_config('trusted_operator_tools', False) is True

    def handle(action, args):
        try:
            if not tools_allowed():
                raise ValueError('Model tools require enabled=true and trusted_operator_tools=true; no per-user authorization is provided')
            spec = specs[action]
            if set(args) - set(spec['properties']):
                raise ValueError('Unknown arguments; routing and state paths are operator-only')
            if not set(spec['required']) <= args.keys():
                raise ValueError('Required argument missing')
            if any(not isinstance(v, str) for v in args.values()):
                raise ValueError('Arguments must be strings')
            if action == 'workflow':
                return json.dumps({'executed': False, 'tool': 'workflow',
                                   'request': workflow_request(args['prompt'])})
            cfg = read_settings()
            if not all(isinstance(cfg[k], str) and cfg[k].strip() for k in ('queue_path', 'tenant', 'profile')):
                raise ValueError('Operator must configure queue_path, tenant, profile')
            q = Queue(cfg['queue_path'])
            scope = (cfg['tenant'], cfg['profile'])
            if action == 'submit':
                job = q.submit(*scope, args['conversation'], args['message'], args['prompt'], args.get('lane', 'background'))
            elif action == 'status':
                job = q.get(*scope, args['job_id'])
            else:
                job = q.cancel(*scope, args['job_id'])
            return json.dumps(public_job(job), ensure_ascii=False)
        except (ValueError, KeyError, OSError) as exc:
            return json.dumps({'error': str(exc)})

    string = {'type': 'string'}
    specs = {
        'submit': {'properties': {'conversation': string, 'message': string, 'prompt': string,
                                 'lane': {'type': 'string', 'enum': ['interactive', 'background']}},
                   'required': ['conversation', 'message', 'prompt']},
        'status': {'properties': {'job_id': string}, 'required': ['job_id']},
        'cancel': {'properties': {'job_id': string}, 'required': ['job_id']},
        'workflow': {'properties': {'prompt': string}, 'required': ['prompt']},
    }
    descriptions = {
        'submit': 'Explicitly queue a standalone task; does not launch a worker. Stable conversation/message IDs required. Not automatic chat offload.',
        'status': 'Read a task in this operator-configured scope. Shared trust domain, not per-user authorization.',
        'cancel': 'Cancel queued work or request worker stop. Running effects may be unknown; no automatic replay.',
        'workflow': 'Build a request for the existing workflow tool for a long task; does not execute or enqueue. Call workflow separately after approval.',
    }
    for action, spec in specs.items():
        name = f'teams_{action}'
        schema = {'name': name, 'description': descriptions[action],
                  'parameters': dict(type='object', additionalProperties=False, **spec)}
        ctx.register_tool(name=name, toolset='teams', schema=schema,
                          handler=lambda args, _action=action, **kwargs: handle(_action, args),
                          check_fn=tools_allowed,
                          description=descriptions[action])
