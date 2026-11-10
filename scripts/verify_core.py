"""Run the official core regression runner in a private credential-free home."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', required=True)
    parser.add_argument('--scratch', required=True)
    parser.add_argument('--timeout', type=float, default=500)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('tests', nargs='+')
    args = parser.parse_args()
    core = Path(args.core).resolve(strict=True)
    tests = []
    for value in args.tests:
        path = Path(value)
        path = path.resolve() if path.exists() else (core / path).resolve(strict=True)
        tests.append(str(path.relative_to(core)))
    root = Path(tempfile.mkdtemp(prefix='official-core-regression-', dir=args.scratch))
    for part in ('home', 'state', 'tmp'):
        (root / part).mkdir()
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ}
    env.update(HOME=str(root / 'home'), HERMES_HOME=str(root / 'state'),
               HERMES_TEST_SANDBOX_HOME=str(root / 'state'), TMPDIR=str(root / 'tmp'),
               HERMES_PYTHON=sys.executable, HERMES_TEST_FILE_RETRIES='0')
    command = ['bash', 'scripts/run_tests.sh', '-j', str(args.jobs), *tests]
    output = root / 'output.txt'
    print('EVIDENCE=' + str(root), flush=True)
    with output.open('w') as stream:
        proc = subprocess.Popen(command, cwd=core, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            code = 124
    (root / 'receipt.json').write_text(json.dumps({'command': command, 'core': str(core),
        'exit_code': code, 'scope': 'offline official core runner; no live provider/platform'}, indent=2))
    print(output.read_text()[-16000:])
    return code


if __name__ == '__main__':
    raise SystemExit(main())
