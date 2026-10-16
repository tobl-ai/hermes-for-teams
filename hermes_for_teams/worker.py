"""Explicit opt-in local worker; process isolation is NOT a security sandbox."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def hermes_command(settings, job):
    if settings.get('allow_cli_workers') is not True:
        raise ValueError('CLI workers require explicit operator allow_cli_workers=true')
    profile = settings.get('profile', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', profile):
        raise ValueError('Invalid operator profile')
    executable = Path(settings.get('hermes_executable', ''))
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('Pin an absolute executable hermes_executable')
    from .gateway_query import owner_paths
    homes = owner_paths(settings)
    if homes is not None:
        control_home, profile_home = homes
        return [sys.executable, str(Path(__file__).with_name('gateway_query.py')),
                '--control-home', str(control_home), '--profile-home', str(profile_home),
                '--cwd', str(Path.cwd()), '--prompt', job['payload']]
    # No arbitrary argv, provider replacement, auth copy, approvals bypass, or local fallback.
    return [str(executable), '--profile', profile, 'chat', '-Q', '--format', 'stream-json', '-q', job['payload']]


def validate_hermes_result(output):
    results = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('type') == 'result':
            results.append(value)
    if len(results) != 1:
        raise ValueError('No unique terminal Hermes result; an admission receipt is not completion')
    result = results[0]
    if (result.get('exit_code') != 0 or not result.get('session_id') or result.get('error')
            or not isinstance(result.get('text'), str) or not result['text'].strip()):
        raise ValueError('Hermes terminal result is incomplete or failed')
    return result['text']


def _group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _stop(proc):
    for sig, delay in ((signal.SIGTERM, .5), (signal.SIGKILL, .2)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=delay)
        except subprocess.TimeoutExpired:
            pass
        if not _group_exists(proc.pid):
            break
    proc.wait()


def run_one(queue, tenant, profile, lane, command_factory, timeout=300, result_validator=None):
    """The callable is an internal test seam, not exposed to model tools or CLI."""
    if not 0 < timeout <= 86400:
        raise ValueError('Timeout must be in (0,86400]')
    job = queue.claim(lane, lease=30, scope=(tenant, profile))
    if job is None:
        return False
    proc = None
    uncertain = False
    try:
        # File output avoids a full pipe deadlock; bounded result read avoids RAM blowups.
        # Owner-only file is inside the private internal queue directory, never T9.
        with tempfile.TemporaryFile(dir=queue.path.parent) as output:
            proc = subprocess.Popen(command_factory(job), stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                state = queue.heartbeat(tenant, profile, job['id'], job['token'], lease=30)
                if state == 'cancel_requested' or time.monotonic() >= deadline:
                    uncertain = True
                    _stop(proc)
                    break
                # A noisy subprocess must not fill the local disk indefinitely.
                if os.fstat(output.fileno()).st_size > 2 * 1024 * 1024:
                    uncertain = True
                    _stop(proc)
                    break
                time.sleep(min(.05, timeout))
            if _group_exists(proc.pid):
                uncertain = True
                _stop(proc)
            uncertain = uncertain or proc.returncode != 0
            output.seek(0)
            result = output.read(65536).decode('utf-8', errors='replace')
        if result_validator is not None and not uncertain:
            result = result_validator(result)
        queue.finish(tenant, profile, job['id'], job['token'], result, uncertain=uncertain)
    except BaseException as exc:
        if proc is not None:
            _stop(proc)
        # Even spawn failures are conservatively unknown. Never auto-retry side effects.
        try:
            queue.finish(tenant, profile, job['id'], job['token'],
                         f'Worker stopped: {type(exc).__name__}', uncertain=True)
        except ValueError:
            pass  # An expired lease is already unknown and cannot be overwritten.
        if not isinstance(exc, Exception):
            raise
    return True
