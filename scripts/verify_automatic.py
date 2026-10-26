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
    parser.add_argument('--timeout', type=float, default=120, help='Bounded offline test deadline in seconds')
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
    command = [sys.executable, '-m', 'pytest', *args.tests, '-o', 'addopts=', '-o', 'faulthandler_timeout=30', '-q']
    output = root / 'pytest-output.txt'
    with output.open('w') as stream:
        try:
            result = subprocess.run(command, cwd=args.core, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    check=False, text=True, timeout=args.timeout)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    (root / 'receipt.json').write_text(json.dumps({'scope': 'offline synthetic fixtures; no live provider/platform',
                                                  'command': command, 'exit_code': exit_code}, indent=2))
    print(output.read_text())
    print('EVIDENCE=' + str(root))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
