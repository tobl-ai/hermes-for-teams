# Contributing and reproducible checks

Use a branch, preserve the official Hermes remote, and do not put credentials,
production paths, account records, customer text or live databases in this repo.
Tests must use private disposable homes and never run inference implicitly.

## Standalone checks (Python 3.10+, POSIX)

```sh
python -m pip install . pytest
python -m pytest tests -q -o addopts=
python -m pip wheel . --no-deps --wheel-dir /private/scratch/wheels
```

Tests requiring Hermes skip when the corresponding core layout is unavailable;
that is not a passing native integration claim. CI separately checks clean
upstream-patch application on Windows and Linux.

## Native integration

Choose a matching isolated Hermes checkout, not the live installation's working
directory. The installed Python wrapper can bootstrap a new managed environment
when cwd is the installed source root; that startup is not pytest progress.

```sh
python scripts/verify_automatic.py --core /path/to/isolated-modern-hermes --scratch /private/scratch /absolute/path/to/this-repo/tests
python scripts/verify_automatic.py --core /path/to/patched-1fd18277 --scratch /private/scratch /absolute/path/to/this-repo/tests/test_legacy_compat.py /absolute/path/to/this-repo/tests/test_legacy_policy.py /absolute/path/to/this-repo/tests/test_compat_cli.py
python scripts/verify_native.py --hermes /absolute/path/to/hermes --scratch /private/scratch --uv-cache /path/to/dependency-cache
```

The native installer verifier uses an independent credential-free home and actual
file-URL install/load/update/disable/remove. Reuse only a dependency cache, never
credentials, and do not restart a Gateway to make a fixture connect.

For exact-upstream patch-only checks without importing Hermes, set
`HERMES_COMPAT_SOURCE` to a checkout containing public commit
`1fd18277267152893a8a24792b79213e7ca3f899` and run
`python -m pytest tests/test_compat_cli.py -q`.

Write regression tests first, record the expected failure, implement, rerun and
obtain independent review. Run public CI before publishing a stable release.
Live provider/platform validation is separately authorized and budgeted; do not
hide a missing live acceptance gate behind a synthetic test or version label.
