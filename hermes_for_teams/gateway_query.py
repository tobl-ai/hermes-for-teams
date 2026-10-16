"""Explicit, existing-owner-only transport for multiplexed Hermes installs.

This opt-in adapter uses the installed programmatic client/frontend contract.
It never starts an owner, retries a prompt or falls back to local inference.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Direct execution puts this package directory (which contains queue.py) first
# on sys.path. Remove that one entry before asyncio imports stdlib queue.
if __name__ == '__main__' and not __package__:
    _script_dir = Path(__file__).resolve().parent
    sys.path = [p for p in sys.path if Path(p).resolve() != _script_dir]

import argparse
import asyncio
import uuid


def owner_paths(settings):
    control = settings.get('existing_owner_control_home')
    profile = settings.get('existing_owner_profile_home')
    if not control and not profile:
        return None
    if not all(isinstance(p, str) and p and Path(p).is_absolute() and Path(p).is_dir()
               for p in (control, profile)):
        raise ValueError('Both existing-owner homes must be explicit absolute existing directories')
    return Path(control).resolve(), Path(profile).resolve()


def check_contract(description, profile_home):
    if description.get('profile_id') != str(Path(profile_home).resolve()):
        raise ValueError('Existing owner bound a different profile')
    creation = description.get('session_create') or {}
    if 'oneshot' not in creation.get('sources', []):
        raise ValueError('Existing owner does not support oneshot sessions')
    if not {'cwd', 'title', 'request_id'} <= set(creation.get('parameters', [])):
        raise ValueError('Existing owner creation contract is incompatible')


async def query(control_home, profile_home, prompt, cwd):
    # Import only on this explicitly opted-in path. Hermes itself owns authentication,
    # session authority, approvals, finite completion and event handling.
    from hermes_cli.gateway_runtime_discovery import query_identify
    from hermes_cli.gateway_runtime import _endpoint
    from hermes_cli.gateway_client import connect_gateway
    from hermes_cli.gateway_chat_view import GatewayChatView
    from hermes_cli.stream_json import StreamJsonEmitter

    descriptor = await asyncio.to_thread(query_identify, control_home, timeout=3)
    target = _endpoint(descriptor, profile_home, control_home=control_home)
    if target.state != 'ready' or target.endpoint is None:
        raise ValueError('Configured existing owner is not ready; no startup attempted')
    async with connect_gateway(endpoint=target.endpoint) as client:
        check_contract(await client.rpc('runtime.describe'), profile_home)
        snapshot = await client.rpc('session.create', request_id=uuid.uuid4().hex,
                                    source='oneshot', cwd=str(cwd), title='Teams explicit queued task')
        # Source/default route is selected by the authenticated profile owner.
        # No model/provider/auth overrides or approvals bypass are injected.
        emitter = StreamJsonEmitter(model=str((snapshot.get('info') or {}).get('model') or ''),
                                    session_id=snapshot['stored_session_id'])
        view = GatewayChatView(client, snapshot, quiet=True, emitter=emitter)
        view.unattended = False  # Preserve chat -q approval policy; never imply YOLO.
        return await view.run(prompt, oneshot=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--control-home', required=True)
    parser.add_argument('--profile-home', required=True)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--prompt', required=True)
    args = parser.parse_args(argv)
    try:
        homes = owner_paths({'existing_owner_control_home': args.control_home,
                             'existing_owner_profile_home': args.profile_home})
        return asyncio.run(query(*homes, args.prompt, Path(args.cwd).resolve()))
    except Exception as exc:
        # No tickets, transport URLs, credentials or full exceptions in task results.
        import json
        print(json.dumps({'type': 'result', 'session_id': '', 'exit_code': 1,
                          'text': '', 'error': 'Existing-owner adapter failed: ' + type(exc).__name__}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
