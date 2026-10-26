# Hermes for Teams

Version **1.0.0** — bounded native-turn scheduling and a durable operator task queue
for Hermes Agent. Keep the official Hermes installation and update remote; no fork
or replacement provider is required. Not endorsed by Nous Research.

## What it does

**Automatic scheduling** wraps a supported Hermes native execution path. Ordinary
requests need no `teams_submit` call. Hermes retains sender authorization, original
input and attachments, session history, approvals, controls and reply delivery.
Independent sessions can execute concurrently; a shared conversation retains its
native ordering. Separate interactive/background reservations bound concurrent
turns, including after a timeout while the physical executor is still alive.

**The explicit queue** is a separate operator feature: persistent SQLite admission,
FIFO per conversation, atomic multi-process claims, message-key deduplication,
heartbeats, stale-worker fencing, cancellation and conservative crash recovery.
It does not resume a shared Hermes conversation or replace native chat history.

### Supported boundaries

- Native plugin installation: an existing Hermes with directory-plugin and CLI
  registration APIs. Automatic scheduling additionally needs the checked core
  connection below; plugin installation alone does not enable it.
- Automatic core connections: exact upstream commit
  `1fd18277267152893a8a24792b79213e7ca3f899`, and the previously verified local
  `0bf79b848b526017e5ce4e5e5535fe0c4782a1cf` / patched `e457d6d7…` layout.
  Unknown versions fail closed. See [compatibility](compat/README.md).
- Explicit queue/workers: **macOS and Linux/POSIX**, Python 3.10+. They require
  owner-only file permissions and process-group termination. Windows patch
  application is tested separately; Windows operator queues are not supported.
- Default automatic capacity: two interactive turns plus one background turn per
  profile/event loop. Input size is a lane heuristic, **not execution-time prediction**.
- No cross-server worker placement, global provider-account quota manager,
  per-user authorization for operator tools, or guarantee of 100 simultaneous
  model responses within a latency target. Backpressure cannot create CPU/RAM or
  provider entitlement. The [release criteria](docs/release-criteria.md) distinguish
  tested software behavior from service-capacity acceptance.

## Install

```sh
hermes --profile YOUR_PROFILE plugins install tobl-ai/hermes-for-teams --enable
hermes --profile YOUR_PROFILE plugins list
hermes --profile YOUR_PROFILE teams doctor
```

Use an existing profile and review the custom-source/dependency consent prompt.
For reproducibility, use `--ref` with the release's **full 40-character commit SHA**;
a tag name is not accepted by Hermes' pin option. Existing pinned installations
must be deliberately updated/reinstalled to the new SHA. Installation never
copies auth, changes models, starts workers or silently restarts the Gateway.

### Enable automatic scheduling

From this repository (or the native plugin's installed Git directory), check the
**actual Hermes source root**, not the profile directory. On Windows, substitute
paths such as `C:/path/to/hermes-agent`.

```sh
python scripts/compat.py check --hermes /path/to/hermes-agent
python scripts/compat.py apply --hermes /path/to/hermes-agent --backup-dir /private/internal/backups
```

The helper checks the exact revision and every hunk, preserves unrelated files,
backs up affected source outside the checkout and verifies the result. No force
patches, upstream update, configuration changes or lifecycle actions are hidden
inside it. Reapplying is a no-op. `source_status: ready` does **not** establish
runtime activation. New Hermes versions may require a new connection.

Merge these settings into the target profile, preserving unrelated keys:

```yaml
plugins:
  entries:
    hermes-for-teams:
      settings:
        automatic_enabled: true
        automatic_interactive: 2
        automatic_background: 1
        automatic_heavy_bytes: 4096
        trusted_operator_tools: false
        allow_cli_workers: false
```

Use the exact owner's supported activation/restart lifecycle during authorized
maintenance. Do not start a second standalone Gateway for a multiplexed profile.
Verify the replacement runtime revision and a real request with fresh
`teams_auto enter` / `teams_auto leave` log records. `teams doctor` is an offline
configuration diagnostic, not proof of runtime or provider health. Shared-room
sessions are **not** silently split by user; doing so changes collaboration history.

## Explicit operator queue

This is an **owner/admin interface**, not an untrusted multi-user tool boundary.
Tenant/profile are configured namespaces, not authenticated user identities.
Model tools are disabled by default; enabling them gives trusted operators within
that scope shared read/cancel access. Do not treat caller-supplied conversation or
message IDs as user authorization. See [security](SECURITY.md).

```yaml
plugins:
  entries:
    hermes-for-teams:
      settings:
        enabled: true
        trusted_operator_tools: false
        tenant: trusted-team
        profile: YOUR_PROFILE
        queue_path: /absolute/private/internal/teams/queue.db
        allow_cli_workers: false
        hermes_executable: /absolute/path/to/hermes
```

Use private internal storage: directory mode `0700`, DB mode `0600`, correct
ownership. External `/Volumes/` and immediate symlinks are rejected. Never put
live state in the public checkout, shared remote SQLite or unencrypted external
storage. Prompts/results are stored in plaintext; configure retention and backups
according to your organization. Do not store credentials in task payloads.

```sh
hermes --profile YOUR_PROFILE teams submit --conversation c1 --message event1 --lane interactive --prompt 'A reviewed task'
hermes --profile YOUR_PROFILE teams status
hermes --profile YOUR_PROFILE teams get JOB_ID
hermes --profile YOUR_PROFILE teams cancel JOB_ID
```

Only after verifying the intended profile, provider and approval route, explicitly
opt in to `allow_cli_workers: true`. Workers invoke the pinned Hermes executable,
never add `--yolo`, replace the provider or use local inference as a fallback.
Run a small bounded number of workers per lane, not 100 heavyweight CLI processes.

```sh
hermes --profile YOUR_PROFILE teams worker --lane interactive --watch
hermes --profile YOUR_PROFILE teams worker --lane background --watch
```

Each explicit job starts a fresh CLI turn. A conversation ID provides ordering,
not memory continuity. Modern Hermes may attach the CLI to its existing owner;
subprocess separation is **not** proof of whole-turn isolation or a security sandbox.
The optional existing-owner adapter is version-specific, not required for automatic
chat scheduling. `teams_workflow` only builds a structurally checked handoff for
an independently installed workflow tool; it neither runs nor queues that workflow.

### Recovery contract

Successful jobs require a unique terminal Hermes result, session ID, zero exit
code and nonempty text. A queued/admitted receipt is not success.

`queued → running → succeeded`; queued cancellation becomes `cancelled`.
Timeouts, crashes, expired leases, running cancellation, ambiguous results and
missing acknowledgments become **`unknown`, never automatically replayed**.
Unknown work keeps its reservation and blocks later work in that conversation.
Killing a CLI does not prove that its underlying Gateway or external effects stopped.

After verifying the real worker stopped and reconciling external effects:

```sh
hermes --profile YOUR_PROFILE teams recover
hermes --profile YOUR_PROFILE teams resolve JOB_ID --note 'Verified worker stopped and effects reconciled'
```

Resolution closes the old job without retrying it. Its idempotency key stays
reserved. Exactly-once external writes require destination-side idempotency and
receipts; an agent's success text does not prove every write occurred.
Capacity policy is persisted at queue creation. Drain/reconcile before changing
it, then explicitly create a new queue. The CLI does not silently reset live state.

## Test, update, remove

```sh
python -m pytest tests -q -o addopts=
python scripts/verify_native.py --hermes /absolute/path/to/hermes --scratch /private/internal/scratch --uv-cache /path/to/uv-cache
hermes --profile YOUR_PROFILE plugins update hermes-for-teams
hermes --profile YOUR_PROFILE plugins disable hermes-for-teams
hermes --profile YOUR_PROFILE plugins remove hermes-for-teams
```

Native verification uses credential-free disposable homes and performs real
install/load/update/disable/remove operations without inference or Gateway restart.
See [verification](docs/verification.md), [compatibility](compat/README.md) and
[contributing](CONTRIBUTING.md) for native integration tests and reproducible scope.

Disabling/removing the plugin does not kill independent workers or delete state.
Stop watch workers, reconcile uncertain work and preserve the queue before removal.
A standalone `python -m pip install .` supplies `hermes-teams --config SETTINGS.json`
for the operator queue; native automatic mode requires the matched Hermes/plugin
pair above. Keep existing isolation policies rather than weakening them for CLI access.

License: [MIT](LICENSE). Changes: [CHANGELOG](CHANGELOG.md).
