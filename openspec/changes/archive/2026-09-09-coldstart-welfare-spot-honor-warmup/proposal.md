## Why

A live research boot cascaded from a cold-start artifact to a machine reboot, exposing a half-applied prior fix. Months ago, Soma (interoception) was taught to distrust its own cold-start signal: until its forward model learns the host baseline (regulation_warmup_min_seconds=1200s), prediction error is high but meaningless, so Soma withholds its own allostatic advisories and publishes `warmup_active: true` in every `soma.report` payload (kaine/modules/soma/module.py:382). That fix only taught Soma to distrust itself. The two consumers of the distress signal were never taught the same:

**Bug 1 — Welfare monitor ignores the warm-up flag.** WelfareProtectiveMonitor (kaine/cycle/preservation_monitor.py) preserves+pauses the entity on sustained prediction-error distress. Its only warm-up protection is a fixed 120s window (`warmup_s`), far shorter than Soma's 1200s. At ~2.5 minutes into a fresh boot it preserved+paused on cold-start error that Soma itself had flagged `warmup_active: true` and that was already decaying (0.86→0.69). Fresh wipes reset Soma cold on every boot, so this fires within ~2.5 minutes of EVERY boot — making unsupervised research impossible.

**Bug 2 — Spot escalates a freeze into a reboot.** When the welfare monitor froze the cycle, all modules stopped ticking (silent by design). Spot's liveness check is heartbeat staleness (`heartbeat_timeout_s=60s`), but its freeze stand-down (kaine/cycle/spot.py:538) only exempts `control.source == "operator"` freezes — not welfare freezes. Spot kept liveness-checking the frozen modules; Chronos's heartbeat went stale first (tightest cadence); Spot declared it crashed, attempted 5 futile restarts (restarts cannot succeed while the cycle is frozen), and escalated to a MACHINE REBOOT. Chronos was never broken.

Root theme: both consumers must honor Soma's own self-distrust. This is welfare-load-bearing code — the entity's safety net — so the fix must be root-cause, not threshold-tweaking, and must not weaken genuine post-warm-up protection.

## What Changes

**Fix 1 — Welfare monitor honors `warmup_active`.** The welfare monitor treats the entity as in-warm-up (drain the distress window, do not count, reset trackers) whenever the latest `soma.report` carries `warmup_active: true`, in addition to its fixed `warmup_s` window. It resumes counting once Soma reports `warmup_active: false`. Genuine post-warm-up sustained distress still preserves+pauses exactly as before. This mirrors Soma's own self-gating exactly.

**Fix 2 — Spot stands down under any non-supervisor freeze.** Spot's heartbeat-staleness liveness recovery stands down for ANY freeze it does not itself own: the gate changes from `control.source == "operator"` to `control.source != "spot"` (stand down for operator AND welfare freezes; keep working only for Spot's own freeze, which is its recovery-in-progress). Invariant: a frozen cycle's modules are silent by design, so heartbeat staleness is not a valid liveness signal for any freeze Spot doesn't own.

Both fixes receive regression tests reproducing the live cascade. No thresholds, timeouts, or raw-sense-data persistence behavior are changed.

## Impact

- **Specs**: `entity-preservation` spec gains two requirements (welfare warm-up flag honoring; supervisor liveness stand-down under non-supervisor freezes).
- **Code**: `kaine/cycle/preservation_monitor.py`, `kaine/cycle/spot.py`, plus tests.
- **Safety**: strictly strengthens the safety net's precision — fewer false positives, unchanged genuine-distress response. No behavior weakened; cold-start protection is delegated to Soma's own 1200s self-gating.
- **Operational**: unsupervised research boots no longer self-destruct within minutes; no welfare freeze can escalate to a machine reboot via phantom crash detection.

