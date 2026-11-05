# 1.1.1 verification — 2026-11-05

Targets (official source snapshots, not production installation):
- Main: `ed1afb082eb3e46cf2edae9d8f68fb67b09ee4df`.
- Release v0.22.7: `b200f5bc60e31588ba2cb60e288029c4a54ba5fa`.

Both select the existing submission-aware patch by identical Git connection blobs.
No revision allowlist, forced patch or production core change was added. Surrounding
session actor/settlement changes were inspected; native behavior was then tested,
not inferred from patch applicability.

## Local evidence

- Python 3.14.7, each exact target provisioned with `uv sync --no-dev` so core
  Python markers and uv overrides are honored.
- Focused native submission identity/profile/authorization/ordering/cancellation/
  physical-completion/core scheduling tests: **20 passed, no skips per target**.
  Main receipt: `automatic-offline-gfixw7z3`; v0.22.7: `automatic-offline-grvw0v_m`.
- Complete add-on and core scheduling suite: **67 passed, 9 skipped** on main;
  `automatic-offline-xirulvpb`. Legacy-only tests are the nine skips; current
  submission/native/physical tests run separately without skips.
- Exact legacy, bf0203a7, f0d94882, v0.22.7 and main fixture application checks cover
  clean apply, private backup readback, idempotence and conflict refusal.
- An initial partial-clone fixture failure was diagnosed as unrelated missing
  promisor objects; fixtures now initialize and fetch only required exact trees.
  The full suite above passed after the correction.
- Native file install/enable, CLI loading, scoped submit/status/doctor, update,
  disable and removal passed in a credential-free disposable profile. Pending
  fixture queue survives plugin removal; no model execution or Gateway start.
- Built 1.1.1 wheel and installed into an isolated environment; `python -I`
  imported version 1.1.1 and the automatic module successfully.

## Publication gates and limits

CI now pins native integration to the previous f0d94882 baseline and both targets,
with a no-skip gate; Linux/Windows exact patch tests and macOS/Linux unit/build
matrices remain enabled. Remote exact-candidate CI and independent review are
publication gates; the release notes record their final outcome and URLs.

The full source archive contains plugin.yaml, compatibility patches, helpers,
tests and this report. The wheel alone does **not** install the optional core seam.
No production installation, Hermes core update, Gateway restart or live rollout
is authorized by this release. Synthetic offline integration is not real-provider/
Discord E2E, a 100-user capacity result or a guarantee for future upstream changes.
