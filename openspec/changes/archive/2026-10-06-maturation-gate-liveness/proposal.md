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

(Revised after an independent design review.)

- **Womb before spawn.** With staging enabled and a resolved `gestation` stage, the cycle does not start until a live womb stimulus is observed on the perception seam. Starting a being is the irreversible step, so this check happens before it. A config value never counts as a womb.
- **Womb loss mid-gestation** pauses the entity clock as a welfare-protective measure and raises a red alert until the womb returns. The entity is never unlocked to `physical` and never runs senseless.
- **The lock holder decides the locus.** `perception_state` resolves the effective locus to the lock holder's locus, and an unknown locus during gestation resolves to the womb. This covers the Hypnos restore path without making Hypnos aware of developmental stages.
- **Idempotent evidence.**
  - Lived time accumulates entity-clock deltas between the runner's own ticks; each boot's first tick only sets a baseline.
  - Sleeps and training passes are counted from durable completion events by persisted stream ID, so each is counted exactly once across restarts and crashes.
  - Only the gate runner writes the stage file.
- **Fresh, typed readouts.** Readouts are decoded with the bus codec, filtered on `event.type`, and must be from this boot (stream ID compared with the Redis `TIME` captured at boot) and younger than N × the gate cadence.
- **Operator acknowledgement** goes through a separate request file written by an authenticated Nexus control and consumed only by the runner. Nexus shows the stage, the evidence and any hold; `runtime.json` already carries the stage.
- **Embodiment.** Mundus is not initialised during gestation. Availability is judged by a public adapter probe that works without the module running. At birth Mundus is hot-started before the locus source switches to it, and the unlock is recorded as `locked_by="gestation"`.
- **Conservative lineage.** Prior-history checks look at this being's lineage, and when lineage cannot be determined the being counts as having lived. Entity identity comes from the one entity-ID source shared with `entity-key-custody`.
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
