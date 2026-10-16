# Optional Hermes core connection

Automatic mode in v0.2 requires `gateway_turn_execution`, an optional local
extension that is not yet an upstream Hermes API. The explicit queue remains
usable without it. This is not a Hermes fork or an upstream endorsement.

The two patches were exported from the verified local source based on
`0bf79b848b526017e5ce4e5e5535fe0c4782a1cf`. The scheduling implementation is
`e457d6d756c3132ba4f0440a12d2004717b6630a`. They also include a narrow existing
onboarding annotation import fix. They are not guaranteed to apply to arbitrary
future Hermes revisions.

For another installation, first identify its exact Hermes checkout and runtime,
back up local changes, inspect these patches and run `git apply --check` against
that checkout. Do not force a patch that does not apply. Only apply the reviewed
patches during an authorized maintenance procedure, run the included tests, then
install/enable the plugin's automatic settings and activate idle owners using
Hermes' supported lifecycle. Keep the official `origin` remote intact.

A plugin install alone does not apply these patches or reload existing Gateways.
An updater may conflict with local changes; review compatibility and restore the
patches against the exact new source rather than force-resetting user changes.

The middleware carries the native result and a separate `physical_completion`
future. A timeout may return while an executor still runs. Capacity must remain
reserved until the physical future completes, not merely until the continuation
coroutine returns. Unknown process outcomes require operator reconciliation.

Do not enable this on a runtime that forbids plugin middleware under its existing
safe-worker/isolation policy. Do not weaken that policy to make activation pass.
