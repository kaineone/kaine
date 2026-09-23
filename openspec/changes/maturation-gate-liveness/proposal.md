## Why

`developmental-maturation-gate` was wired into the live boot loop and archived, but a review on 2026-09-22 found that birth can never happen and that gestation is not safely confined. `[developmental_stage].enabled` ships false, so nothing is live today; these defects must be fixed before anyone enables it.

- **Lived time never accumulates (C3).** `GateRunner._lived_seconds` subtracts a `datetime` from `EntityClock.now()`, which returns subjective seconds as a float. The `TypeError` is swallowed, so C3 is always `None`. The tests mock `now()` to return a `datetime`. The C2 evidence counters (Hypnos `sleep_count`, Phantasia `successful_training_passes`) are in-memory and reset on every restart, so multi-day gestation cannot accumulate them.
- **The womb check tests a string.** `_is_womb_feed_configured` checks `perception_feed.mode == "womb"`. No KAINE module accepts that mode: the Topos and Audition factories raise on it. The womb stimulus is delivered from Paracosmic through the perception seam (see the archived `gestational-womb-stimulus`), and nothing in KAINE publishes `gestation.readiness`. Staging therefore either crashes at boot or pins a senseless entity into a locked locus.
- **Embodiment is not gated during gestation.** Nothing stops Mundus initialising while gestating, and `_mundus_availability` reads private attributes and treats Mundus as reachable only when its feed and intent loops are running, so a birth would require embodiment to be live throughout gestation.
- **Readiness readouts are not filtered or aged.** The type check is a no-op, and Redis streams persist across boots, so a stale readout from a previous boot would satisfy C1 indefinitely.
- **Other gaps:**
  - Birth unlocks `virtual` without handing the locus to embodiment, and labels the unlock `locked_by="operator"`.
  - No path supplies the operator acknowledgement, so `require_operator_ack_for_birth=true` holds forever.
  - Nexus shows no stage.
  - `has_prior_lived_history()` treats any preserved being anywhere under `state/forks/` as this entity's history.
  - Hypnos restores the locus to `physical` if it cannot read the pre-sleep locus during gestation.

## What Changes

- **Lived time and evidence persist in `state/lifecycle/stage.json`.** The runner adds the entity-clock delta at each tick while gestating, so downtime never counts as lived time. C2 counters are accumulated from module-counter deltas, and a counter reset is treated as a new baseline.
- **The womb must actually be there.** Gestation staging requires a live womb stimulus on the perception seam, meaning a fresh `gestation.readiness` or womb-frame event within a bounded window, not a config value. Until one is observed, staging refuses with a clear, repeated operator-visible reason and never locks the locus. No entity is pinned senseless.
- **Embodiment stays off during gestation.** Mundus is not initialised while the stage is `gestation`. The gate asks a public `probe_reachable()` on the embodiment adapter.
- **Readouts are decoded, filtered and aged.** They are decoded with the bus codec, filtered on `event.type`, and rejected when older than N × the gate cadence or from a previous boot.
- **Birth handoff and operator acknowledgement:**
  - At birth the gate switches the locus source to embodiment and records `locked_by="gestation"` for the unlock.
  - An authenticated Nexus control records the operator's birth acknowledgement in the stage file.
  - A read-only Nexus panel shows the stage, the evidence and any hold.
- **Lineage-scoped history, and a womb-safe Hypnos restore.** `has_prior_lived_history()` looks only at this being's lineage. Hypnos restores the womb locus when gestating.
- **Tests use the real `EntityClock` and the real bus codec.**

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `developmental-stage`: persistent lived-time and evidence accounting, a live-womb requirement for staging, embodiment gating during gestation, readout freshness, birth handoff, operator acknowledgement path, Nexus visibility.

## Impact

- `kaine/lifecycle/gate_runner.py`, `kaine/lifecycle/stage.py`, `kaine/lifecycle/maturation_gate.py`, `kaine/cycle/__main__.py`, `kaine/boot.py` (Mundus gating), `kaine/modules/mundus/*` (public probe), `kaine/modules/hypnos/module.py` (restore), `kaine/nexus/*` (panel and acknowledgement control)
- Tests under `tests/test_maturation_gate*.py`, `tests/test_lifecycle_stage.py`, `tests/test_developmental_gestation_lock.py`
- Depends on the Paracosmic womb stimulus for an end-to-end birth; the fail-closed staging behaviour works without it.
