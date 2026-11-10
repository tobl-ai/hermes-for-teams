"""Disposable addon wheel lifecycle smoke; never installs into a live Hermes env."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--uv', default=shutil.which('uv'))
    args = parser.parse_args()
    if not args.uv:
        parser.error('--uv requires an available uv executable')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='wheel-lifecycle-', dir=os.environ['TMPDIR']))
    (root / 'home').mkdir()
    (root / 'tmp').mkdir()
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ}
    env.update(HOME=str(root / 'home'), TMPDIR=str(root / 'tmp'))
    uv = args.uv
    commands = []
    result = {'status': 'started', 'evidence': str(root), 'commands': commands}
    def run(argv, expect=0, cwd=None):
        result = subprocess.run(argv, cwd=cwd or root, env=env, capture_output=True, text=True, timeout=120)
        commands.append({'argv': argv, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode != expect:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout
    try:
        run([uv, 'build', '--wheel', '--out-dir', str(output), str(repo)])
        wheels = list(output.glob('*.whl'))
        if len(wheels) != 1:
            raise RuntimeError('Expected exactly one unreleased wheel')
        wheel = wheels[0]
        run([uv, 'venv', '--python', sys.executable, str(root / 'env')])
        python = str(root / 'env/bin/python')
        cli = str(root / 'env/bin/hermes-teams')
        run([uv, 'pip', 'install', '--python', python, str(wheel)])
        config = root / 'settings.json'
        queue = root / 'private/queue.db'
        config.write_text(json.dumps({'tenant': 'offline-wheel', 'profile': 'tobl', 'queue_path': str(queue),
                                     'allow_cli_workers': False}))
        args = [cli, '--config', str(config)]
        first = json.loads(run([*args, 'submit', '--conversation', 'c', '--message', 'm', '--prompt', 'do not execute']))
        assert first['state'] == 'queued'
        assert json.loads(run([*args, 'status']))['jobs'] == 1
        run([uv, 'pip', 'install', '--python', python, '--reinstall', str(wheel)])
        assert json.loads(run([*args, 'status']))['jobs'] == 1
        run([uv, 'pip', 'uninstall', '--python', python, 'hermes-for-teams'])
        run([python, '-I', '-c', 'import importlib.util; assert importlib.util.find_spec("hermes_for_teams") is None'])
        assert queue.exists()
        result = {'status': 'passed', 'scope': 'Unreleased wheel install/reinstall/remove only; no native same-thread or provider certification',
                  'wheel': str(wheel), 'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  'evidence': str(root), 'commands': commands}
    except BaseException as exc:
        result = {'status': 'failed', 'error': str(exc), 'evidence': str(root), 'commands': commands}
        raise
    finally:
        (output / 'wheel-lifecycle.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != 'commands'}, indent=2))


if __name__ == '__main__':
    main()
