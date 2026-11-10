"""Tested-layout core compatibility patches. Never updates or restarts Hermes."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHSETS = {
    'f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab': ['submission-f0d94882.patch'],
    'bf0203a794a07aac3ff764972ab9087baa4e4f4e': [
        '0002-feat-connect-native-turns-to-optional-scheduling-mid.patch'],
    '1fd18277267152893a8a24792b79213e7ca3f899': ['legacy-1fd18277.patch'],
    '0bf79b848b526017e5ce4e5e5535fe0c4782a1cf': [
        '0001-fix-import-Path-before-onboarding-handler-annotation.patch',
        '0002-feat-connect-native-turns-to-optional-scheduling-mid.patch'],
    'e457d6d756c3132ba4f0440a12d2004717b6630a': [
        '0001-fix-import-Path-before-onboarding-handler-annotation.patch',
        '0002-feat-connect-native-turns-to-optional-scheduling-mid.patch'],
}


def git(home, *args):
    return subprocess.run(['git', '-C', str(home), *args], check=False, capture_output=True, text=True,encoding='utf-8')


def inspect(home, capability='automatic'):
    home = Path(home).expanduser().resolve()
    top = git(home, 'rev-parse', '--show-toplevel')
    if top.returncode or Path(top.stdout.strip()).resolve() != home:
        raise ValueError('--hermes must identify the actual checkout root')
    head = git(home, 'rev-parse', 'HEAD').stdout.strip()
    selected = None
    capabilities = ['automatic']
    registry = json.loads((ROOT / 'compat/registry.json').read_text(encoding='utf-8'))
    if registry.get('schema') != 1:
        raise ValueError('Unsupported packaged capability registry')
    for layout in registry['layouts']:
        if capability not in layout['capabilities']:
            continue
        matches = True
        for path, expected in layout['blobs'].items():
            actual = git(home,'ls-tree','HEAD','--',path)
            fields = actual.stdout.split()
            blob = fields[2] if fields else None
            if actual.returncode or blob != expected:
                matches = False
                break
        if matches:
            selected = layout['patches']
            capabilities = layout['capabilities']
            break
    if selected is None and capability == 'same-thread':
        raise ValueError('Unsupported Hermes execution layout for same-thread capability: ' + head +
                         '; no source or configuration changed')
    if selected is None:
        selected = PATCHSETS.get(head)
    if selected is None:
        # Permit unrelated upstream updates, but not unreviewed execution changes.
        # Compare the tracked connection modules, not a version string or merely
        # whether fuzzy patch context happens to apply.
        for baseline, names in PATCHSETS.items():
            if git(home, 'cat-file', '-e', baseline + '^{commit}').returncode:
                continue
            paths = set()
            for name in names:
                for line in (ROOT / 'compat' / name).read_text(encoding='utf-8').splitlines():
                    if line.startswith('+++ b/'):
                        paths.add(line[6:])
            matches = True
            for path in paths:
                # Compare Git blob IDs: text-mode `git show` would normalize
                # CRLF/CR and incorrectly accept distinct connection sources.
                # ls-tree succeeds with empty output only for absent paths;
                # any actual Git error is a refusal, never 'both absent'.
                expected = git(home, 'ls-tree', baseline, '--', path)
                actual = git(home, 'ls-tree', 'HEAD', '--', path)
                if expected.returncode or actual.returncode or expected.stdout != actual.stdout:
                    matches = False
                    break
            if matches:
                selected = names
                break
        if selected is None:
            raise ValueError('Unsupported Hermes execution layout: ' + head +
                             '; connection modules differ from tested layouts; no source or configuration changed')
    patches = [str(ROOT / 'compat' / name) for name in selected]
    applied = git(home, 'apply', '--reverse', '--check', '--', *patches)
    if applied.returncode == 0:
        return home, head, patches, 'ready', capabilities
    check = git(home, 'apply', '--check', '--', *patches)
    if check.returncode:
        raise ValueError('Patch conflicts with this working tree; refused without changes:\n' + check.stderr)
    return home, head, patches, 'needs_patch', capabilities


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
        for line in Path(name).read_text(encoding='utf-8').splitlines():
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
    (backup / 'files.json').write_text(json.dumps(inventory, indent=2),encoding='utf-8')
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
    parser.add_argument('--capability', choices=['automatic','same-thread'], default='automatic')
    args = parser.parse_args()
    try:
        home, head, patches, status, capabilities = inspect(args.hermes,args.capability)
        backup = None
        if args.action == 'apply' and status == 'needs_patch':
            backup = apply(home, patches, args.backup_dir)
            status = 'ready'
        print(json.dumps({'hermes_commit': head, 'source_status': status,
                          'capabilities': capabilities, 'requested_capability': args.capability,
                          'patches': [Path(p).name for p in patches], 'backup': backup,
                          'runtime_activated': False,
                          'note': 'Source check only; install plugin, opt in and use authorized native lifecycle separately.'}))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc), 'runtime_activated': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
