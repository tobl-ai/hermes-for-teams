# Release criteria and service-capacity boundary

## 1.0 software scope

The supported product is a version-pinned native scheduling connection and an
owner/admin queue. Its safety invariants are:

1. Original native authorization, profile scope, message objects, attachments,
   session ordering, approvals and delivery remain owned by Hermes.
2. Concurrent independent turns are bounded; physical executor work keeps its
   seat after coroutine timeout. Re-registration must not create fresh capacity
   while old reservations are live. Capacity changes require drained work.
3. Explicit jobs use atomic claims, FIFO, idempotency and fencing. Uncertain
   attempts are held, not automatically replayed. No forged successful result.
4. Installation is opt-in, dependency-consented and reversible. Removal preserves
   state. Model tools/workers are off by default. No credential/model migration.
5. Core patches are exact-revision checked with clean-apply, conflict refusal,
   private backup and idempotence tests. Unsupported versions/platform features
   fail clearly rather than forcing a patch or weakening isolation.
6. Native installation lifecycle, POSIX queue/worker tests, legacy integration
   and modern regression tests pass. Public CI verifies declared OS/Python lanes
   and installable wheels. An independent review must close mandatory findings
   before stable publication.

Keep the release SHA, CI results and verification commands in release notes.
Do not call an unrun lane verified. Historical evidence is not a new-version test.

## Activation and upgrades

Prepare/test source, install the plugin, persist settings, then use the exact
owner's native maintenance lifecycle. Record old/new runtime identities and run
a fresh request. Re-registration preserves capacity but is not a substitute for
restarting after code/ABI changes: an existing scheduler instance may keep its
old class until the owner restarts. Do not interrupt unrelated work for a test.

## Not a 100-user service acceptance certificate

A stable software release does not establish account entitlement, 100 simultaneous
provider calls, regional/network latency, deployment RAM capacity, arbitrary tool
workloads, or human messaging E2E. Those depend on the installation and provider.
The original 100-human serving objective must remain open until its own staged
acceptance passes; publishing 1.0 does not close it.

For deployment acceptance, use explicit authorized budgets and staged real-model
requests, with 429/provider-error and memory-pressure stop conditions. Report
successful terminal receipts, first/useful/final latency, queue wait, retained
unknown work and actual resource measurements. Include tools, same-session
follow-ups, cancellation and destination-side idempotency checks for external
writes. Never reinterpret synthetic sleep/queue/fixture counts as live users.

Same-room ordering is a deliberate collaboration policy. User-specific sessions
must be an explicit deployment decision, not a silent optimization that discards
shared context. Backpressure protects the host; it cannot promise unlimited speed.
