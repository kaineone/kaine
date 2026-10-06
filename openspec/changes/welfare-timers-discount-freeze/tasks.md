## 1. Primitive
- [x] 1.1 `kaine/cycle/unfrozen_clock.py`: `UnfrozenClock` per the design.

## 2. Arms
- [x] 2.1 Protective monitor: `unfrozen_clock` for sustained distress and the warm-up; wall `clock` kept for cadence and rate limits.
- [x] 2.2 Welfare observer: unfrozen time for sustained distress, sustained extreme VAD and unmaintained fatigue.
- [x] 2.3 `InputLossWatcher`: staleness in unfrozen time.
- [x] 2.4 Wiring in the cycle and the sidecar registry (one clock per process).
- [x] 2.5 Warm-up ceiling bound on wall time so a freeze during warm-up cannot blind the monitor forever.
- [x] 2.6 `SustainedThresholdTracker` counts wall time up to the last sample plus unfrozen time since the last sample.
- [x] 2.7 `InputLossWatcher._baseline` retries after a failed `bus.latest` and does not count leftover entries as fresh.
- [x] 2.8 Cycle boot creates one shared `UnfrozenClock` and passes it to both the welfare monitor and the input watcher.

## 3. Tests (real `control_state` freeze, `tmp_path` state root, injected monotonic; each mutation-checked by removing the discount)
- [x] 3.1 A distress sample just before a 60 s freeze does not cross; the same sample with no freeze crosses at 30 s.
- [x] 3.2 Sustained distress samples continuing through a freeze cross after 30 s of unfrozen time, counted across the freeze.
- [x] 3.3 A below-threshold sample during a freeze resets the run.
- [x] 3.4 Windowed repeat events delivered during a freeze still count.
- [x] 3.5 Warm-up is not consumed by a freeze.
- [x] 3.6 Observer extreme-VAD and fatigue arms do not fire across a freeze.
- [x] 3.7 Input loss: a freeze with inputs off sends no notice; inputs that stay silent after release are reported after the threshold of unfrozen time.
- [x] 3.8 `UnfrozenClock`: `unknown_counts_as` has no default; with `"unfrozen"` a corrupt control file keeps time counting; one warning per unknown episode and a `diagnostic()`; transitions attributed within one poll; cached read within `poll_s`.
- [x] 3.9 A corrupt `control.json` plus a distress run still crosses at the threshold (mutation-checked by flipping the policy).
- [x] 3.10 Every welfare caller passes `unknown_counts_as="unfrozen"` (a test inspects the constructed clocks).

## 4. Docs
- [x] 4.1 The welfare chapter and the caretaker section state that welfare timers count unfrozen time, and why.
- [x] 4.2 `design.md` and the welfare-monitoring spec name the `freeze_state_unreadable` incident-log record and the evaluation-sink diagnostic as the surfaced unreadable-state surfaces.
