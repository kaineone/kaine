# Tasks — coldstart-welfare-spot-honor-warmup

## 1. Welfare monitor honors the interoceptive warm-up flag (Bug 1)
- [ ] 1.1 In `WelfareProtectiveMonitor`, capture the latest `soma.report.warmup_active` as reports are drained (both the warm-up-drain and the main soma.out drain paths).
- [ ] 1.2 Extend the warm-up gate in `_poll_once`: treat the entity as in warm-up (drain-and-do-not-count, reset trackers) when the fixed `warmup_s` window is active OR the latest `soma.report.warmup_active` is true.
- [ ] 1.3 Resume counting the moment Soma reports `warmup_active: false`; genuine post-warm-up sustained distress preserves+pauses unchanged.

## 2. Supervisor liveness stands down under any non-supervisor freeze (Bug 2)
- [ ] 2.1 In `Spot._poll_once`, change the freeze stand-down from `control.source == "operator"` to `control.source != "spot"` (stand down for operator AND welfare freezes; keep working only for Spot's own recovery freeze). Comment the invariant: a frozen cycle's modules are silent by design, so heartbeat-staleness is not a valid liveness signal for a freeze Spot does not own.

## 3. Tests
- [ ] 3.1 Welfare: sustained distress with `warmup_active: true` → NO preserve/pause (drained); then `warmup_active: false` + sustained distress → DOES preserve+pause.
- [ ] 3.2 Spot: stale-heartbeat module under a `welfare`-sourced freeze → stands down (no incident/escalation); under `operator` → stands down; under `spot` → still assesses; unfrozen + stale → assesses (unchanged).

## 4. Docs
- [ ] 4.1 `docs/processes/entity-preservation.md` + `docs/operations.md`: the welfare net and Spot both honor the interoceptive cold-start warm-up (present tense).
