"""Exact-revision, checked core compatibility patches. Never updates or restarts Hermes."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHSETS = {
    '1fd18277267152893a8a24792b79213e7ca3f899': ['legacy-1fd18277.patch'],
    '0bf79b848b526017e5ce4e5e5535fe0c4782a1cf': [
        '0001-fix-import-Path-before-onboarding-handler-annotation.patch',
        '0002-feat-connect-native-turns-to-optional-scheduling-mid.patch'],
    'e457d6d756c3132ba4f0440a12d2004717b6630a': [
        '0001-fix-import-Path-before-onboarding-handler-annotation.patch',
        '0002-feat-connect-native-turns-to-optional-scheduling-mid.patch'],
}


def git(home, *args):
    return subprocess.run(['git', '-C', str(home), *args], check=False, capture_output=True, text=True)


def inspect(home):
    home = Path(home).expanduser().resolve()
    top = git(home, 'rev-parse', '--show-toplevel')
    if top.returncode or Path(top.stdout.strip()).resolve() != home:
        raise ValueError('--hermes must identify the actual checkout root')
    head = git(home, 'rev-parse', 'HEAD').stdout.strip()
    if head not in PATCHSETS:
        raise ValueError('Untested Hermes revision: ' + head + '; no source or configuration changed')
    patches = [str(ROOT / 'compat' / name) for name in PATCHSETS[head]]
    applied = git(home, 'apply', '--reverse', '--check', '--', *patches)
    if applied.returncode == 0:
        return home, head, patches, 'ready'
    check = git(home, 'apply', '--check', '--', *patches)
    if check.returncode:
        raise ValueError('Patch conflicts with this working tree; refused without changes:\n' + check.stderr)
    return home, head, patches, 'needs_patch'


def apply(home, patches, backup_dir):
    if backup_dir is None:
        raise ValueError('apply requires --backup-dir outside the checkout')
    destination = Path(backup_dir).expanduser().resolve()
    if destination == home or home in destination.parents:
        raise ValueError('--backup-dir must be outside the checkout')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='teams-compat-', dir=destination))
    paths = set()
    for name in patches:
        for line in Path(name).read_text().splitlines():
            if line.startswith('+++ b/'):
                relative = Path(line[6:])
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Invalid packaged patch path')
                paths.add(relative)
    inventory = {}
    for relative in sorted(paths):
        source = home / relative
        if not source.resolve().is_relative_to(home):
            raise ValueError('Patched file escapes checkout through a symlink')
        inventory[str(relative)] = source.exists()
        if source.exists():
            out = backup / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, out)
            out.chmod(0o600)
    (backup / 'files.json').write_text(json.dumps(inventory, indent=2))
    (backup / 'files.json').chmod(0o600)
    # git apply without --reject is fail-closed; never force hunks or reset user work.
    result = git(home, 'apply', '--', *patches)
    if result.returncode:
        raise ValueError('Apply failed; inspect backup ' + str(backup) + ': ' + result.stderr)
    verify = git(home, 'apply', '--reverse', '--check', '--', *patches)
    if verify.returncode:
        raise ValueError('Source readback failed; inspect backup ' + str(backup))
    return str(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'apply'])
    parser.add_argument('--hermes', required=True)
    parser.add_argument('--backup-dir')
    args = parser.parse_args()
    try:
        home, head, patches, status = inspect(args.hermes)
        backup = None
        if args.action == 'apply' and status == 'needs_patch':
            backup = apply(home, patches, args.backup_dir)
            status = 'ready'
        print(json.dumps({'hermes_commit': head, 'source_status': status,
                          'patches': [Path(p).name for p in patches], 'backup': backup,
                          'runtime_activated': False,
                          'note': 'Source check only; install plugin, opt in and use authorized native lifecycle separately.'}))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc), 'runtime_activated': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
