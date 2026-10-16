"""Exercise native file:// install + directory load in a disposable credential-free home.

Uses installed official Hermes; never restarts a gateway or runs inference.
Run: python scripts/verify_native.py --hermes /absolute/path/to/hermes
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hermes', required=True)
    parser.add_argument('--scratch', required=True, help='Private internal disposable workspace')
    parser.add_argument('--uv-cache', help='Reuse an existing dependency cache (not credentials)')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='hermes-teams-native-', dir=args.scratch) as temp:
        root = Path(temp)
        source = root / 'hermes-for-teams'
        source.mkdir()
        for name in ('__init__.py', 'plugin.yaml', 'pyproject.toml'):
            shutil.copy2(repo / name, source / name)
        shutil.copytree(repo / 'hermes_for_teams', source / 'hermes_for_teams', ignore=shutil.ignore_patterns('__pycache__'))
        def run(argv, env=None, cwd=None, expect=0):
            try:
                proc = subprocess.run(argv, env=env, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            except subprocess.TimeoutExpired as exc:
                print((exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout)
                raise
            print('$', ' '.join(argv).replace(str(root), '<TEMP>'))
            print(proc.stdout.replace(str(root), '<TEMP>'))
            assert proc.returncode == expect, (proc.returncode, proc.stdout)
            return proc.stdout
        run(['git', 'init', '-q', str(source)])
        run(['git', '-C', str(source), 'add', '.'])
        run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Native install fixture'])
        home = root / 'home'
        profile = home / 'profiles' / 'tobl'
        profile.mkdir(parents=True)
        (profile / 'config.yaml').write_text('{}')
        fake_user = root / 'user'
        fake_user.mkdir()
        env = {'PATH': os.environ['PATH'], 'HOME': str(fake_user), 'TMPDIR': str(root), 'HERMES_HOME': str(home),
               'HERMES_DISABLE_UPDATE_CHECK': '1', 'PYTHONIOENCODING': 'utf-8'}
        if args.uv_cache:
            env['UV_CACHE_DIR'] = str(Path(args.uv_cache).resolve())
        command = [args.hermes, '--profile', 'tobl']
        run(command + ['plugins', 'install', source.as_uri(), '--yes-deps', '--enable'], env)
        installed = profile / 'plugins' / 'hermes-for-teams'
        assert (installed / 'hermes_for_teams' / 'queue.py').is_file()
        listing = run(command + ['plugins', 'list', '--plain', '--no-bundled'], env)
        assert 'hermes-for-teams' in listing and 'enabled' in listing
        settings = {'enabled': True, 'tenant': 'fixture', 'profile': 'tobl',
                    'queue_path': str(root / 'private' / 'queue.db'), 'allow_cli_workers': False}
        # Profile-scoped operator settings; no production profile is modified.
        config = {'plugins': {'enabled': ['hermes-for-teams'], 'isolation': 'in_process',
                             'entries': {'hermes-for-teams': {'enabled': True, 'settings': settings}}}}
        (profile / 'config.yaml').write_text(json.dumps(config))
        run(command + ['teams', '--help'], env)
        status = run(command + ['teams', 'status'], env)
        assert '"jobs": 0' in status
        run(command + ['teams', 'doctor'], env)
        output = run(command + ['teams', 'submit', '--conversation', 'c', '--message', 'm', '--prompt', 'fixture: do not execute'], env)
        assert '"state": "queued"' in output
        status = run(command + ['teams', 'status'], env)
        assert '"jobs": 1' in status
        manifest = source / 'plugin.yaml'
        manifest.write_text(manifest.read_text().replace('version: 0.1.0', 'version: 0.1.1'))
        run(['git', '-C', str(source), 'add', '.'])
        run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Update fixture'])
        run(command + ['plugins', 'update', 'hermes-for-teams'], env)
        assert 'version: 0.1.1' in (installed / 'plugin.yaml').read_text()
        run(command + ['plugins', 'disable', 'hermes-for-teams'], env)
        listing = run(command + ['plugins', 'list', '--plain', '--no-bundled'], env)
        assert listing.strip().startswith('disabled') and 'hermes-for-teams' in listing
        run(command + ['plugins', 'remove', 'hermes-for-teams'], env)
        assert not installed.exists()
        assert (root / 'private' / 'queue.db').exists(), 'Removal must preserve pending work for operator reconciliation'
        print('NATIVE_FIXTURE_PASS: file install+enable, loader CLI, scoped submit/status, doctor, update, disable, remove; no provider execution')


if __name__ == '__main__':
    main()
