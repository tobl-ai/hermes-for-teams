# Hermes for Teams — explicit queue/worker add-on

**Public experimental alpha — not a production-ready 100-user chat server.**

다른 Hermes 설치본에 **포크 없이 애드온으로 설치·시험**할 수 있습니다. 단, 설치만으로 일반 Discord 대화가 자동 분산되거나 100명 동시 사용 성능이 보장되지는 않습니다. 운영 전체가 아닌 별도 시험 프로필부터 적용하세요.

A standalone native Hermes plugin and a stdlib-only Python CLI. No patched core, provider middleware,
monkeypatches, daemon installed on load, or automatic gateway interception.

## Implemented behavior

- Durable owner-local SQLite admission queue, with separate reserved
  `interactive` (2) and `background` (1) slots by default. Multiple worker
  processes share atomic capacity and claim decisions through one internal DB.
- Idempotency on `(tenant, profile, message)`; reusing that key with different
  prompt/conversation/lane is rejected rather than silently losing new input.
- FIFO within `(tenant, profile, conversation)`, including across lanes.
  Independent conversations can run concurrently. A long task in *another*
  conversation does not occupy the interactive reservation.
- Explicit opt-in worker executes the pinned official
  `hermes --profile PROFILE chat -Q --format stream-json -q PROMPT` path.
  It never switches model/provider, copies auth, adds `--yolo`, invokes a shell,
  or falls back to local in-process inference. A terminal JSON result, session ID,
  exit code 0 and nonempty response are required; a queue receipt is not success.
- Scoped operator CLI: submit/get/status/cancel/recover/resolve/worker/doctor.
- Optional model-facing tools, **off by default**, for trusted operator-only
  sessions. The plugin opens neither queue nor worker during registration.
- A request builder for the existing `hermes-workflows` tool. Its output passes
  the catalog-pinned upstream structural validator. **This is grammar-compatible
  handoff preparation, not a running workflow or verified workflow reuse.**

## Safety / supported release scope

**Do not expose these tools to an untrusted multi-user gateway.** Tenant/profile
are operator-configured routing namespaces, not authenticated user identities.
The public tool handler used here has no validated Discord sender/tenant binding.
Conversation/message IDs are caller supplied, and all trusted operators in one
configured scope can read or cancel its jobs. A model can forge another ID in
that same scope. For this reason `trusted_operator_tools: false` hides *all* model
tools and rejects direct handler invocation, even when the queue itself is enabled.
Opting in explicitly accepts this shared trust domain; it does not fix authorization.

The CLI is an owner/admin surface. An OS user who can read the DB or operator
settings is trusted. Python subprocesses are **not a security sandbox**. Do not
share one OS credential identity among mutually untrusted tenants. Queue queries
check tenant/profile scope, but the DB owner can access all rows. This add-on does
not authorize external writes; the configured Hermes runtime retains its normal
approval policy. It does not broaden an existing unattended/yolo configuration.

Live queue storage must be internal, with directory mode 0700, file mode 0600,
and correct ownership. `/Volumes/` and immediate symlinks are rejected. It stores
plaintext prompts/results, not credentials. Use a dedicated private directory;
never place it in the public checkout, unencrypted external storage, a remote
shared filesystem, or share live Hermes session SQLite between workers.

A conversation here is a **scheduling key**, not resumed Hermes chat history.
Each job launches a fresh CLI turn. FIFO does not claim conversation/session
migration. A modern official CLI may itself attach to the profile's existing
Gateway owner: isolating that CLI process does **not** prove a whole agent turn
or tools moved into a separate execution process. Only submitted jobs use this
queue; ordinary Discord/Telegram traffic bypasses it completely.

## Failure, cancellation and reconciliation

States: `queued -> running -> succeeded`; queued cancellation becomes
`cancelled`; running cancellation becomes `cancel_requested -> unknown`.
Expired leases, nonzero exits, timeouts, ambiguous/missing terminal results and
interrupted workers become `unknown`, **never automatically replayed**.
Unknown work retains its lane seat and blocks later work in that conversation.
A CLI can detach while its Gateway work still exists: killing the CLI alone is
not proof that the underlying turn stopped.

An operator must verify the real owner/worker stopped and reconcile external
writes, then use `resolve JOB_ID --note 'verified disposition ...'`. This closes
as `resolved`, never retries the original message. Reusing the same idempotency
key still returns the original job. Start genuinely new work only with a new
message ID after reconciliation. No queue can promise exactly-once remote writes
without destination-side idempotency/receipts; this package deliberately chooses
no automatic retry over replaying uncertain effects. A normal completed turn is
not independently verified proof of every external write it describes.

`recover` conservatively marks expired attempts unknown, not queued. Disabling
or removing the plugin does not kill independent worker processes or delete
pending state. Stop workers, reconcile running/unknown attempts, and preserve
state before removal. `--watch` workers must be explicitly stopped by the operator.
Capacity policy is persisted at queue creation; mismatched explicit policies
are rejected. Limits are across this queue only, not provider-account/global-host
limits. Changing limits requires draining and explicitly creating a new queue.

## Install on another Hermes

Public repository: https://github.com/tobl-ai/hermes-for-teams

Replace `YOUR_PROFILE` with an existing **test profile** on the target installation:

```sh
hermes --profile YOUR_PROFILE plugins install tobl-ai/hermes-for-teams --ref v0.1.0 --enable
hermes --profile YOUR_PROFILE plugins list
hermes --profile YOUR_PROFILE teams --help
```

This is the **v0.1.0 experimental prerelease**. Installing does not start workers,
copy authentication, change models or route ordinary conversations into the queue.
Hermes may ask for approval for this non-catalog source and its package metadata.
Configure the target profile as below before `teams status` / `teams doctor`.
For an already-running Gateway, schedule normal activation when idle; do not
restart it from inside an active task just to load this alpha.

## Local installation and smoke verification

Python >=3.10; native plugin verification was on the installed official runtime.
macOS tested; Linux declared but not exercised on a Linux host in this run.
The native verifier creates a disposable local Git source,
a separate credential-free `HERMES_HOME` and a `tobl` fixture profile. It exercises
real official file-URL installation with dependency consent and enable, load,
submit/status/doctor, an actual source update, disable, read-back and removal.
It never restarts a gateway or calls a model. The initial install may resolve
Hermes dependencies and require network/cache access.

```sh
python -m pytest -q -o addopts='' --basetemp "$PRIVATE_SCRATCH/teams-tests" tests
python -m hermes_for_teams.cli --help
hermes --profile tobl plugins validate . --json
python scripts/verify_native.py --hermes /absolute/path/to/hermes \
  --scratch "$PRIVATE_SCRATCH" --uv-cache /absolute/path/to/uv-cache
python scripts/verify_workflow_grammar.py --scratch "$PRIVATE_SCRATCH"
```

Set `PRIVATE_SCRATCH` to private **internal** disposable storage. The optional
workflow grammar probe downloads and imports one pinned third-party validator
into its temporary directory; review that source before running it. No third-party
engine is vendored or automatically installed by this package.

For a reviewed local checkout, `python -m pip install .` provides `hermes-teams`.
A directory plugin has root `plugin.yaml` and `register(ctx)`; settings are read
only via public `ctx.get_config`. Use the pinned prerelease installation above
for experiments. Do not modify the official Hermes update remote.

## Operator configuration

Place settings under `plugins.entries.hermes-for-teams.settings` in the target
profile's `config.yaml`, preserving unrelated configuration:

```yaml
plugins:
  entries:
    hermes-for-teams:
      settings:
        enabled: true
        trusted_operator_tools: false
        tenant: trusted-team
        profile: tobl
        queue_path: /absolute/internal/private/teams/queue.db
        allow_cli_workers: false
        hermes_executable: /absolute/path/to/hermes
```

These are operator choices, not tool parameters. Enable the plugin itself using
its normal installation/activation flow; the settings flag does not install it.
Native `hermes teams` CLI requires in-process plugin loading; host-isolation
capability probing reports CLI registration is skipped in the plugin host. The
standalone `hermes-teams --config SETTINGS.json` surface is independent of that.
Do not weaken a production isolation policy merely to expose this CLI.

```sh
hermes --profile tobl teams doctor
hermes --profile tobl teams submit --conversation c1 --message event1 \
  --lane background --prompt 'Standalone long task'
hermes --profile tobl teams status
hermes --profile tobl teams get JOB_ID
hermes --profile tobl teams cancel JOB_ID
```

Only after verifying the exact target profile/owner, current provider route and
approval behavior, explicitly set `allow_cli_workers: true`. One worker invocation
processes jobs sequentially until none are claimable; launch a small bounded
number per lane, never 100 heavyweight Hermes processes on a small workstation.

```sh
hermes --profile tobl teams worker --lane interactive --watch
hermes --profile tobl teams worker --lane background --watch
```

`doctor` is an offline scope/route-configuration diagnostic, not inference,
auth, isolation, remote-write, or throughput verification. It reports unsupported
claims as false. JSON standalone settings use the same keys:
`hermes-teams --config /private/settings.json status`.

For a trusted operator-only profile, `trusted_operator_tools: true` exposes
`teams_submit`, `teams_status`, `teams_cancel`, `teams_workflow` under the `teams`
toolset (subject to Hermes toolset selection). It does not start workers.
`teams_workflow` returns `{executed:false,tool:'workflow',request:...}`. The
operator must separately review and invoke an installed workflow tool. Do not
also enqueue that same work here and claim its separate runner is bounded by
this queue. See [reuse assessment](docs/reuse-assessment.md).

## Compatibility / remaining gates

Public interfaces used: directory `register(ctx)`, `ctx.get_config`,
`ctx.register_tool`, `ctx.register_cli_command`, and the official chat CLI's
stream-json terminal contract. No private core imports in package code.
No claim of compatibility with releases lacking these behaviors.

Remaining blockers to the original 100-human goal:

1. Authenticated per-user ingress and result delivery, tenant membership, trusted
   conversation/message derivation and cancellation authorization.
2. A supported whole-turn ownership/admission/offload interface for the actual
   configured Codex/Gateway path. Model middleware is neither sufficient nor
   used as an enforcement substitute here.
3. Real provider/approval/session smoke, then staged 1/5/10/25/50/100 load with
   rate-limit and memory-pressure stop conditions, and real messaging E2E.
   These were **not run**. Existing runtime admission/startup uncertainty is not
   an excuse to bypass the owner with a local inference fallback.
4. Real provider/tool/user-authorization security review and production rollout
   gates remain open. Publishing this experimental alpha and verifying installation
   is not production approval. No live installation or gateway restart is implied.

## Update or remove

```sh
hermes --profile YOUR_PROFILE plugins update hermes-for-teams
hermes --profile YOUR_PROFILE plugins disable hermes-for-teams
hermes --profile YOUR_PROFILE plugins remove hermes-for-teams
```

Review versions and canary-test before updates. Stop workers and reconcile unknown
work before removal. The queue database is deliberately not deleted by uninstall.

Not endorsed by Nous Research. License: [MIT](LICENSE).

See [execution evidence](docs/verification.md) for exactly what was exercised.
