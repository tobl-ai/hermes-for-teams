# Version 1.0.0 verification

## Locally exercised release gates

- Modern supported core and add-on regression/authority tests: **61 passed,
  10 skipped**. Skipped cases are not passing acceptance evidence.
- Exact `1fd18277` legacy core integration, policy and clean-patch tests:
  **18 passed**.
- Standalone wheel installed in a clean Python 3.11 environment: **37 passed,
  7 skipped**; `hermes-teams --help` ran from the installed distribution, not
  an import from the source checkout.
- Installable `hermes_for_teams-1.0.0-py3-none-any.whl` built successfully.
- Static undefined-name/syntax checks and secret-signature scan passed.
- Actual native CLI install/enable/load/submit/status/doctor/update/disable/remove
  completed with `NATIVE_FIXTURE_PASS` on the supported patched modern checkout.
  Version 1.0.0 installed, an intentionally modified fixture updated to 1.0.1,
  disabled state and removal were read back. The queued database survived removal.

The native fixture uses a disposable credential-free home and local file-URL Git
source, no model inference and no Gateway restart. Its optional `--uv-cache` shares
only package-cache bytes. Current Hermes PM explicitly selects `<data-root>/cache/uv`
rather than respecting `UV_CACHE_DIR`; the verifier links that cache inside the
throwaway root. Without a warm dependency cache, full SDK provisioning can exceed
its five-minute command timeout. Earlier timed-out cold-cache attempts were not
counted as a successful native lifecycle test.

Public workflows cover macOS/Linux Python 3.10–3.12 standalone tests and wheel
builds, plus Linux/Windows clean upstream patch application. **The workflow run at
the published release SHA is the remote CI evidence**; this local document does
not manufacture a Linux/Windows result before a run completes. Release notes link
that run and the exact source revision.

## What the tests establish

The suite includes multiple real OS processes submitting 100 unique jobs with
repeated idempotency keys; a child exiting after a claim; independent lane
scheduling; cancellation; stale/fabricated lease rejection; actual executor-thread
lifetime checks; native profile/session authority; middleware failure policy;
legacy recursive follow-ups; hot re-registration retaining capacity; automatic-only
diagnostics and bounded terminal-result parsing. These verify software behavior,
not provider throughput or authenticated human messaging delivery.

Core patches are tested against exact supported source trees. The explicit queue
needs no core patch; automatic mode requires the matched connection. The optional
existing-owner transport uses version-specific internal interfaces and is not an
arbitrary-version compatibility guarantee.

## Not established by this release

No 100-human model/tool/Discord end-to-end capacity certificate, provider-account
quota guarantee, universal latency target, cross-server worker placement or
per-chat-user ACL for operator tools. Explicit jobs are fresh turns and do not
inherit native conversation memory. Host-isolated plugin loading may omit CLI
registration; preserve production isolation instead of weakening it for a test.

A configured plugin or successful offline doctor does not prove runtime activation.
A live rollout requires the exact owner's supported maintenance lifecycle and a
fresh real request. Historical rollout evidence must not be described as a new
1.0.0 deployment. The original 100-user service goal remains separately open until
its own deployment acceptance passes; see [release criteria](release-criteria.md).
