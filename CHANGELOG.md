# Changelog

## 1.0.0

- Establish the supported native scheduler and POSIX operator-queue contracts,
  activation procedure, security model and version-pinned compatibility checks.
- Add the real `1fd18277` legacy native-turn connection without newer session
  modules; preserve physical worker lifetime and recursive native follow-ups.
- Add checked source patching with private backups, idempotence, clean-clone
  verification and conflict refusal. Keep the existing modern connection.
- Preserve native capacity across plugin re-registration, isolate reservations by
  profile/event loop and refuse policy changes while work or waiters remain.
- Fix automatic-only `doctor` operation and distinguish configured from verified
  runtime/provider state. Diagnostics do not create a task database.
- Validate heartbeat lease ranges and reject nonfinite/boolean values before
  changing expiry; preserve stale-worker fencing and conservative recovery.
- Fix terminal result validation after large progress streams, while retaining
  the bounded output limit and uncertain-outcome handling.
- Explicitly reject unsupported non-POSIX operator storage/workers before claiming
  jobs. Add OS/Python, patch-application and distribution-build CI lanes.
- Document that stable software is not a 100-user provider/deployment capacity
  certificate, and does not add cross-server placement or operator-tool user ACLs.

## Earlier development versions

The initial public 0.1.0 release provided an explicit operator queue. Development
0.2 added the modern automatic connection and local rollout. Those historical
prerelease artifacts remain identifiable; they are not the current stable target.
