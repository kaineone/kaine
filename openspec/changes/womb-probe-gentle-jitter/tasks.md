## 1. Implementation

- [x] 1.1 `GestationReadoutConfig`: `perturbation_drive_fraction` (default 0.75; `baseline < value <= 1`) and `probe_jitter_fraction` (default 0.25; `[0, 0.5]`).
- [x] 1.2 `GestationOwner`: perturbation sets `drive.scale = perturbation_drive_fraction`; keyed, seeded jitter on every due time (the first probe of each kind waits an extra `[0, j)` of its period); a `seed` constructor parameter.
- [x] 1.3 Entrypoint passes `[perception_feed].seed`; `config/kaine.toml` and `docs/operations.md` describe the gentler, jittered protocol.

## 2. Verification

- [x] 2.1 Tests: the perturbation scale is the configured fraction, never 1.0 by default; the validation bounds; due times vary within `±j` of the period and are identical for the same seed and different for another; `j = 0` gives the fixed schedule; the settle, spacing and fairness rules still hold under jitter.
- [ ] 2.2 Offline suite green; `openspec validate womb-probe-gentle-jitter --strict` passes.
