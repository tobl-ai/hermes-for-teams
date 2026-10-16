"""Run offline tests in disposable, credential-free homes (no owner start)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', required=True)
    parser.add_argument('--scratch', required=True, help='Private internal disposable scratch directory')
    parser.add_argument('tests', nargs='+')
    args = parser.parse_args()
    scratch = Path(args.scratch).expanduser().resolve()
    if not scratch.is_dir():
        parser.error('--scratch must be an existing private internal directory')
    root = Path(tempfile.mkdtemp(prefix='automatic-offline-', dir=scratch))
    for part in ('home', 'state', 'tmp'):
        (root / part).mkdir()
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ}
    env.update(HOME=str(root / 'home'), USERPROFILE=str(root / 'home'),
               HERMES_HOME=str(root / 'state'), HERMES_TEST_SANDBOX_HOME=str(root / 'state'), TMPDIR=str(root / 'tmp'),
               PYTHONPATH=os.pathsep.join((str(Path(args.core).resolve()), str(Path(__file__).resolve().parents[1]))),
               PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, '-m', 'pytest', *args.tests, '-o', 'addopts=', '-q']
    result = subprocess.run(command, cwd=args.core, env=env, capture_output=True, text=True)
    (root / 'pytest-output.txt').write_text(result.stdout + result.stderr)
    (root / 'receipt.json').write_text(json.dumps({'scope': 'offline synthetic fixtures; no live provider/platform',
                                                  'command': command, 'exit_code': result.returncode}, indent=2))
    print(result.stdout + result.stderr)
    print('EVIDENCE=' + str(root))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
