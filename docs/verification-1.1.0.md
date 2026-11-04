# 1.1.0 local verification

Target: official Hermes source `f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab`.
All source application occurred in a disposable clone, not the installed core.

- RED: exact-source current-layout compatibility regression failed with unsupported layout.
- GREEN: submission-aware connection selected, applied with backup, reverse-checked and idempotent.
- Whole add-on plus packaged core scheduling suite: **65 passed, 9 skipped**.
  Skipped cases are the legacy-only native path, not the current submission test.
  Evidence: `automatic-offline-wc7gxhct` (local verifier evidence directory).
- Focused current submission/native/physical/core scheduling suite: **20 passed, no skips**.
  Evidence: `automatic-offline-5tn_zr89`.
- Exact legacy, bf0203a7 and current f0d94882 clean-source application covered by CLI regressions.
- Blob-identity comparison refuses CRLF-only connection changes and actual Git errors.
- Built `hermes_for_teams-1.1.0-py3-none-any.whl`; installed into a disposable target directory;
  isolated interpreter imported version 1.1.0 and automatic module successfully.
- Focused suite also passed under a freshly provisioned Python 3.14.7 uv environment:
  **20 passed, no skips**, evidence `automatic-offline-ucqf_1oo`. Core's uv
  dependency overrides are required; pip-only provisioning is not equivalent.
- Independent review: required findings closed; final focused CI correction PASS.
- Prepared Linux/Windows patch CI, Python 3.14 current-core integration CI with no-skip gate,
  and daily upstream drift probe. Workflow is local only: remote CI has NOT run and periodic
  upstream checking is NOT active until separately published/enabled.

Installed source read-only check: `needs_patch`, `runtime_activated=false`.
No production core patch, Gateway restart, model/provider change, public push or release occurred.
This is not real-provider/Discord E2E, all-future-version compatibility or 100-user capacity evidence.
The source bundle includes plugin manifest, checked core patches, helper scripts and this report;
the wheel alone does not install the optional core connection.
