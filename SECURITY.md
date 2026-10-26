# Security model

Report vulnerabilities privately to the repository maintainers using GitHub
private vulnerability reporting where enabled. Do not attach credentials, task
payloads, customer conversations or live SQLite databases to public issues.

## Trust boundaries

- The native automatic connection preserves Hermes' authenticated ingress and
  profile/session policy. It is a scheduler, not a replacement authorizer.
- Explicit CLI and model tools are **operator-only**. Tenant/profile and caller
  message/conversation IDs are not authenticated user identities. Trusted
  operators in one scope can read/cancel that scope's jobs. Do not expose these
  tools to mutually untrusted users. Both model tools and workers default off.
- The OS owner can read the queue and settings. Subprocesses, Python ContextVars
  and separate profiles are not OS sandboxes. Use separate OS/container identities
  and a real authorization/control plane for untrusted organizations.
- Private internal queue directory `0700`, database `0600`, correct UID. POSIX
  permissions are required. Payloads/results are plaintext; use organization-
  appropriate storage encryption, backups and retention. No secrets in prompts.
- The patch helper never changes credentials, approval mode, update remotes or
  runtime lifecycle. Core connections are revision-pinned and require review.

## Execution uncertainty

No automated retry of a possibly executed attempt. A crash, timeout, lost result,
expired lease or running cancellation can leave external work alive. Reservations
and conversation order stay blocked until an operator verifies the worker stopped
and reconciles effects. A terminal model result is not proof of every external
write. Exactly-once remote effects require destination-side keys and receipts.

The optional existing-owner adapter uses version-dependent internal Hermes client
surfaces. It checks exact profile binding, preserves approvals and never launches
an owner or falls back to alternate inference. Do not enable it on an unverified
runtime. Keep normal Hermes security and isolation policies unchanged.

Limits are per queue or native profile/event loop, not account-wide provider quota
or host-wide security limits. Host administrators must set deployment resource and
provider budgets. Source installation or offline doctor output is not live safety
or capacity certification.
