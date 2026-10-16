# Reuse assessment and execution boundaries

Official references:
- https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
- https://hermes-agent.nousresearch.com/docs/api/plugin-catalog.json

The live catalog and source were read before implementing this layer. Initial
README/main-branch investigation was followed by the actual catalog-pinned source:

| Candidate | Inspected revision / source | What it actually covers | Decision |
|---|---|---|---|
| IOWAP Hermes integration | `b67e0b276f2215434ecc27ef94f57b82192f6fbe`, `tools/iowap-task` | Local node-cli submission + flock-protected task tracking and desktop relay fleet UI; relay identity belongs to node-cli | Do not invent transparent Discord offload. Relay/node capability, authorization and result delivery were not provisioned/tested. No IOWAP runtime integration is claimed. |
| Hermes Workflows | `b1bf8cc99d5113cfaf8251122ce4f4492838bad8`, `wfcommon.py`, plus tool door and runner inspection | DAG/fan-out/gates/resume, detached runner and child quiet chat CLI, not a general multi-human gateway admission interface | Reuse its documented graph vocabulary in an explicit handoff request builder, not another DAG engine. Pinned structural validator accepts the built graph. Actual workflow tool launch/stop/resume/provider execution remains unverified. |
| Hermes Teammates | `5c6f9cd00df3ddbf105bb06107577ef2945ef047`, `teammates_host.py` | Named in-process subagents via public `ctx.subagent_lifecycle`; parent credentials and tool boundaries | Do not relabel subagents remote workers or 100-user capacity. No teammates engine copy or implicit launch. |

Source links:
- https://github.com/iowap-org/iowap-hermes-integration/blob/b67e0b276f2215434ecc27ef94f57b82192f6fbe/tools/iowap-task
- https://github.com/jacobhausler/hermes-workflows/blob/b1bf8cc99d5113cfaf8251122ce4f4492838bad8/wfcommon.py
- https://github.com/100yenadmin/hermes-teammates/blob/5c6f9cd00df3ddbf105bb06107577ef2945ef047/teammates_host.py

The workflows catalog disclosure also describes agent-authored argv gates outside
the ordinary tool-approval gate, cross-profile read models, detached runners that
survive disable, route probes and API wake turns. Those are not automatically safe
for untrusted tenants. This package emits no argv gate/profile/model override and
never starts that runner. A grammar check is not an approval or behavior audit.

## Why a narrow queue instead of middleware or a fork

The missing independent component is durable explicit-task admission with
separate short/long reservations, cross-process claims, ordering and conservative
crash handling. These behaviors are implemented, not just measured. The add-on
only owns the work explicitly submitted to it.

Inspected installed Hermes `agent/turn_api_call.py` exposes `llm_execution`
on a normal API-call path; the configured Codex external/app-server route is not
proven to pass through it. The wrapper can continue downstream when middleware
raises before `next_call`. It is not a fail-closed whole-turn admission hook.
This package deliberately registers **no middleware**.

Installed public `hermes_cli.gateway_chat`/`gateway_chat_view` support finite
quiet CLI requests attached to an existing Gateway owner and wait for a settled
admission. `stream_json.emit_result` is the terminal record consumed by this
worker. This avoids accepting launch receipts as success, but does not move the
owner's whole turn into the subprocess. A crashed/killed CLI may leave owner
work running, so unknown work keeps its reservation until operator reconciliation.
Top-level `-z` is not substituted: installed oneshot.py documents unattended
auto-approval behavior; this implementation uses only the normal chat surface.

No authorized trusted-sender/session-binding queue ingress or turn-migration hook
was established here. Thus this is explicitly **not** automatic multi-user chat
scaling. A safe production integration requires those boundaries and actual
Codex-path execution proof rather than importing private gateway internals.
