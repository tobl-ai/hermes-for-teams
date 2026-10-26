# Version-checked Hermes core compatibility

Automatic scheduling needs `gateway_turn_execution`, an optional connection
that is not an upstream-released Hermes API. Installing the plugin alone does
not add it. Keep the official upstream remote; this is not a Hermes fork.

## Supported source layouts

- **`1fd18277267152893a8a24792b79213e7ca3f899`** (public upstream):
  `legacy-1fd18277.patch` connects the existing profile-scoped `_run_agent` and
  its real executor's `worker_done` event in `gateway/run_turn.py`. It needs no
  `session_finite.py`, `session_runtime_workers.py`, `session_managed_worker.py`
  or new durable admission subsystem. Native authorization, session ordering,
  approvals, input objects and reply delivery remain native. Recursive queued
  follow-ups share the outer lease instead of acquiring a second seat.
- **`0bf79b848b526017e5ce4e5e5535fe0c4782a1cf`** (previous local layout):
  use the original `0001`/`0002` patches. The verified result is local core
  **`e457d6d756c3132ba4f0440a12d2004717b6630a`**. Do not assume those local
  commits can be fetched from the official upstream.
- Other revisions are refused until ported and tested, not guessed from file
  names or force-patched. Official updates can require a new compatibility port.

The legacy ordinary-chat connection does not provide every newer CLI or the
newer existing-owner RPC adapter. Automatic mode does not require that explicit
queue adapter. The explicit queue is a separate feature.

## Check and apply

From this plugin repository, use Python 3.10+ and the **actual Hermes source
checkout**, not its profile directory. Substitute real local paths; Windows can
use `C:/path/to/hermes-agent`.

```sh
python scripts/compat.py check --hermes /path/to/hermes-agent
python scripts/compat.py apply --hermes /path/to/hermes-agent --backup-dir /private/path/to/backups
python scripts/compat.py check --hermes /path/to/hermes-agent
```

`check` is read-only. `apply` checks exact HEAD and every hunk, saves affected
source files in a private backup outside the checkout, and applies without
reset, force or `--reject`. Conflicts leave source unchanged. Reapplying is a
no-op; unrelated files remain unchanged. Inspect backup `files.json` on restore:
files recorded absent require deliberate removal, not copying a missing backup.

**This only prepares source.** No credentials, settings, remotes, packages or
running Gateways are changed by the helper. After reviewing and testing source,
install/enable plugin **v1.0.0 or later**, opt in with
`plugins.entries.hermes-for-teams.settings.automatic_enabled: true`, and use the
authorized native lifecycle for the exact owner. Keep operator tools/CLI workers
off unless separately needed. Verify new runtime identity plus an actual request
and fresh `teams_auto` records. Source `ready` still reports
`runtime_activated: false`.

Both layouts retain capacity until physical executor completion, not merely a
coroutine timeout. Unknown outcomes must not be replayed. Do not weaken existing
plugin isolation or safe-worker policies to enable the feature.

## Verification and scope

The real `1fd18277` source was exercised locally through `_run_agent` and its
actual worker-start method with a real thread, native result/error preservation
and recursive follow-ups. Clean exact-commit Git clones test dry run, backup,
apply, idempotence, conflict refusal and preservation of unrelated files. CI
patch checks cover Linux and Windows. These are not recipient-PC model/platform
E2E or 100-user throughput evidence; the recipient PC was not changed here.

Shared-room history is **not** changed to user-specific sessions. A shared
session stays ordered; independent sessions can run concurrently. Limits are
per-profile scheduling, not cross-server worker placement.
