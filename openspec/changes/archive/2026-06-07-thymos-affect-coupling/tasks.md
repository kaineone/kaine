## 1. Coupling

- [x] 1.1 Map detected emotion category → VAD target (reuse Thymos's emotion↔VAD table)
- [x] 1.2 `coupling = clamp(coupling_base + coupling_familiarity_gain × familiarity, 0, coupling_ceiling)`; cache latest familiarity per agent from `empatheia.agent_model`
- [x] 1.3 Implement cumulative-drift safeguard: `coupling_max_rate_per_s` rolling-window cap (or cooldown after N consecutive nudges); enforce in the nudge path

## 2. Module wiring

- [x] 2.1 Subscribe Thymos to `audition.emotion` and `empatheia.agent_model`
- [x] 2.2 On `audition.emotion`, nudge dimensional state toward the VAD target by `coupling` (pre-appraisal; preserve drift/hysteresis); skip when `enabled` is false; enforce cumulative-drift safeguard
- [x] 2.3 Graceful fallback to `coupling_base` when no familiarity is known

## 3. Config

- [x] 3.1 `[thymos.coupling]`: `enabled`, `coupling_base`, `coupling_familiarity_gain`, `coupling_ceiling`, `coupling_max_rate_per_s`; update `make_thymos` allowed keys

## 4. Familiarity cache persistence

- [x] 4.1 Include the per-agent familiarity cache in Thymos's `serialize()`/`deserialize()` round-trip so it survives fork restore

## 5. Tests

- [x] 5.1 `tests/test_thymos_coupling.py` — detected emotion shifts VAD toward target; higher familiarity → larger shift; shift bounded by per-step ceiling; disabled → no shift; no-Empatheia → base coupling
- [x] 5.2 `tests/test_thymos_coupling_drift.py` — emotion events at 3.33 Hz toward an extreme for 10 s must NOT leave the dimensional state pinned at the boundary after input stops; drift returns state toward neutral range (bounded recovery)
- [x] 5.3 `tests/test_thymos_coupling_persistence.py` — familiarity cache round-trips through serialize/deserialize; coupling uses cached values on next event
- [x] 5.4 `tests/test_thymos_module.py` — `audition.emotion` consumed; appraisal path unchanged

## 6. Verification

- [x] 6.1 Full unit suite green
- [x] 6.2 `openspec validate thymos-affect-coupling --strict` clean
- [x] 6.3 Commit (Kaine.One), branch-per-change, merge, archive
