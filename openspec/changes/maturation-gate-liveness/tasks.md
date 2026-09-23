## 1. Accounting

- [ ] 1.1 Persist `lived_subjective_seconds`, `sleep_count_total`, `training_passes_total` and last-seen module counters in `stage.json`; accumulate by delta each tick while gestating; treat a module-counter reset as a new baseline.
- [ ] 1.2 Replace `_lived_seconds` with the persisted accumulator; test with the real `EntityClock`, across a simulated restart and a simulated downtime gap.

## 2. Womb presence and embodiment gating

- [ ] 2.1 Replace `_is_womb_feed_configured` with a live-womb probe (fresh womb event within a bounded window); refuse staging with a repeated operator-visible reason until present; never lock the locus without it.
- [ ] 2.2 Skip Mundus initialisation while gestating; add a public `probe_reachable()` on the embodiment adapter and use it in the gate.

## 3. Readiness readouts

- [ ] 3.1 Decode readouts with the bus codec, filter on `event.type`, reject readouts older than N × cadence or from a previous boot; test with the real encoder.

## 4. Birth and operator

- [ ] 4.1 Birth switches the locus source to embodiment and records `locked_by="gestation"` for the unlock.
- [ ] 4.2 Authenticated Nexus control that records the operator's birth acknowledgement; read-only Nexus panel for stage, evidence and hold.
- [ ] 4.3 Scope `has_prior_lived_history()` to this being's lineage; Hypnos restores the womb locus when gestating.

## 5. Verification

- [ ] 5.1 Fix test isolation (`STAGE_PATH` via monkeypatch); cover the repeated no-stimulus warning, the acknowledgement path and welfare-during-gestation.
- [ ] 5.2 Offline suite green; `openspec validate maturation-gate-liveness --strict` passes.
