# Experimental v0.1.0 verification

## Exercised by the implementing agent and separately re-run by the maintainer

- `python -m pytest -q`: **18 passed in 4.90s** on macOS.
- Native lifecycle: `python scripts/verify_native.py --hermes <absolute-hermes> --scratch <private-internal-scratch>` completed with `NATIVE_FIXTURE_PASS`.
- This used a disposable credential-free Hermes home/profile and local file-URL Git source. The test installed/enabled the plugin, listed it enabled at 0.1.0, loaded `teams --help`, ran queue status/doctor/submit, updated a fixture source to 0.1.1 and read it back, disabled and read back disabled, then removed it. The separate queue database remained present after removal.
- The doctor honestly returned automatic chat offload, provider capacity verification and per-user authorization as false.
- No production profile was configured and no gateway was restarted by these tests.

The suite includes five real OS processes submitting 100 unique jobs with repeated idempotency keys; a real process exiting with status 7 after a claim; long/short child-process lane isolation; cancellation; scope mismatch and forged lease-token rejection. These exercise local scheduling, not provider throughput.

## Scope not established

No 100-user model/tool/Discord end-to-end test; no production latency target; no verified remote worker offload; no Linux-host run; no authenticated per-chat-user access control; no preservation of a Hermes session's conversation history across separate queued jobs. A successfully loaded plugin is not certification of any of these.

The native lifecycle test used the installed Hermes checkout's public plugin interface. It is not a matrix certification of pristine upstream releases. Package runtime code imports no Hermes private internals and requires no core patch. Host-isolated plugin loading may omit CLI registration; do not weaken a production isolation setting simply to expose the CLI.

The optional workflow helper prepares a payload only. A structural validator pass is not evidence that an actual workflow engine executed it.

## Publication status

This source is published only as an **experimental prerelease** for operator-controlled test profiles. Production rollout and the original complete 100-user-serving goal remain open. The separately verified remote install result is recorded in the GitHub prerelease notes.
