## 1. Rate-invariant appraisal

- [x] 1.1 `_appraise_snapshot` scales the valence and arousal nudges by `min(4, dt / appraisal_reference_interval_s)`, `dt` from the preceding `_tick`.
- [x] 1.2 Config key `[thymos].appraisal_reference_interval_s` (default 0.3), allowed and validated positive.

## 2. Timer-driven state

- [x] 2.1 A task started in `initialize` runs `_tick` and `_maybe_publish_state` every `publish_interval_s` (subjective seconds, read through the module clock), stopping with the module.

## 3. Tests, docs

- [x] 3.1 Tests: the arousal gained per second from a steady novel coalition is the same at 3.3 and 10 broadcasts per second; state is published with no broadcasts; mutation-check.
- [x] 3.2 Docs: `docs/09-modules/thymos.md`.
- [x] 3.3 `openspec validate thymos-rate-invariant-timely-state --strict`.
