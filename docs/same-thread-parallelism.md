# Same-thread parallel work — approved product update

## Status

User-approved 1.2.0 implementation contract. The 1.1.1 path did not implement it.
The candidate source now provides optional native branches and physical-resource
contracts on the two exact Linux layouts in `compat/registry.json`. Publication,
loaded runtime and actual user-path activation are separate gates; offline tests
do not establish live throughput. This does not remove native session safety.

## User-facing contract

A person must be able to assign independent work in one shared chat/thread without
creating another channel, DM, session, or invoking a special queue command.

- “계약서 검토해 줘” starts task A.
- “별도로 내일 발표 자료도 만들어 줘” starts task B concurrently with A.
- “계약서는 6개월 기준으로 바꿔” steers A only.
- “계약서 작업 멈춰” cancels A only; B continues.
- Ambiguous follow-ups ask which active task; never broadcast an edit/cancellation
  or invent authority from a job/conversation ID supplied in message text.
- Every acceptance, result and control acknowledgment identifies its owning task
  and replies to the original authenticated request in the original thread.
- Conversation remains responsive during development: “했어?”, status queries and
  ordinary questions receive an independent lightweight response while coding
  continues. They must not be blindly steered into the coding worker or queued
  behind its completion. Only actual task edits/stop instructions control that
  worker. Use a safe task-state/context snapshot, not shared mutable transcripts.
- Track execution completion separately from messaging delivery acknowledgment.
  A pending/unknown final delivery must not globally block unrelated question
  intake; never fake delivery success or replay uncertain external sends.

## Capacity

Remove the two-short-request bottleneck. Target a configurable initial policy of
8 interactive and 2 heavy/background reservations per owning profile, subject to
bounded offline verification and live canary/provider/memory stop conditions.
Do not describe this setting as proven model throughput. Preserve existing
explicit installation settings until a drained, authorized activation. Retain
physical-work and unknown reservations after cancellation/timeouts.

## Architecture invariants

1. A shared room is the collaboration surface, not a concurrently writable agent
   transcript. Each independent task has a native isolated execution/history
   branch with a fixed authorized context snapshot and explicit task identity.
   Do not let parallel agents append to one mutable native conversation history.
2. Original sender, profile, scope, source message, attachments, approvals and
   reply route remain native-authority-owned. A routing classifier supplies
   intent, not permissions. No synthetic authorized sender or prompt replay.
3. Ingress routes a new independent request before busy-input steer/queue consumes
   it. Existing task follow-ups retain within-task ordering. Merely increasing
   AutomaticScheduler seats after SessionAuthority FIFO cannot achieve this.
4. Task selection uses reply/message binding or an unambiguous authorized active
   task reference. Cross-profile/conversation/sender controls fail closed according
   to native authorization. Preserve shared collaboration context deliberately;
   do not silently split the room by user.
5. Disjoint work may overlap. Writes to the same canonical resource are serialized
   through actual execution/tool-boundary reservations, not a prompt suggestion.
   Resolve aliases/symlinks; hold reservations until physical completion, including
   unknown workers. Use conservative workspace/global write conflict policy when
   the exact write set is not known. External systems still need their own
   idempotency/receipts; never claim arbitrary exactly-once side effects.
6. Persistent admission and message deduplication cover crash/restart, queued
   controls and unknown execution. No automatic replay of uncertain side effects.
7. Reuse official native APIs and the existing standalone add-on/compatibility
   mechanism. Keep official Hermes update remotes, provider and OAuth unchanged.
   A new seam is a local optional connection, not an upstream feature claim.

## Acceptance gates (all required for feature completion)

- RED→GREEN tests for ordinary-message A/B overlap in one real native shared-room
  ingress, without teams_submit, manual CLI branching, or manual thread splitting.
- Follow-up modifies A only; targeted cancellation stops A only and B completes.
- Ambiguity, unauthorized/cross-scope control, forged task IDs, duplicate ingress,
  attachment/sender preservation, correct task-labeled reply routing.
- Same-task FIFO; isolated transcript snapshots; no lost history or result writes.
- Same-resource writes never overlap while disjoint safe work can overlap.
- Native physical completion, queued/active cancellation, unknown reservation,
  crash reconciliation and plugin re-registration retain correct capacity.
- Configurable >2 native interactive executions; bounded synthetic load and
  explicit real-model/provider/memory measurement reported separately.
- Full add-on regression suite and exact supported-core native integration;
  independent review of the final delta, with mandatory findings closed.
- Compatibility selector, clean install/upgrade and docs must distinguish source,
  saved config, loaded runtime and actual user-path behavior.

## Release/activation boundary

Source implementation, publication after passing gates and scoped Tobl lifecycle
installation were separately authorized. Fleet rollout, credential/model changes
and unrelated/live owner restarts were not. Record any blocked native API or
activation gate explicitly. A tested router class, increased semaphore, spec,
queued card or fresh standalone chat is not this complete feature.
