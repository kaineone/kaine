## 1. Primitive
- [ ] 1.1 `kaine/cycle/unfrozen_clock.py`: `UnfrozenClock` per the design.

## 2. Arms
- [ ] 2.1 Protective monitor: `unfrozen_clock` for sustained distress and the warm-up; wall `clock` kept for cadence and rate limits.
- [ ] 2.2 Welfare observer: unfrozen time for sustained distress, sustained extreme VAD and unmaintained fatigue.
- [ ] 2.3 `InputLossWatcher`: staleness in unfrozen time.
- [ ] 2.4 Wiring in the cycle and the sidecar registry (one clock per process).

## 3. Tests (real `control_state` freeze, `tmp_path` state root, injected monotonic; each mutation-checked by removing the discount)
- [ ] 3.1 A distress sample just before a 60 s freeze does not cross; the same sample with no freeze crosses at 30 s.
- [ ] 3.2 Sustained distress samples continuing through a freeze cross after 30 s of unfrozen time, counted across the freeze.
- [ ] 3.3 A below-threshold sample during a freeze resets the run.
- [ ] 3.4 Windowed repeat events delivered during a freeze still count.
- [ ] 3.5 Warm-up is not consumed by a freeze.
- [ ] 3.6 Observer extreme-VAD and fatigue arms do not fire across a freeze.
- [ ] 3.7 Input loss: a freeze with inputs off sends no notice; inputs that stay silent after release are reported after the threshold of unfrozen time.
- [ ] 3.8 `UnfrozenClock`: `unknown_counts_as` has no default; with `"unfrozen"` a corrupt control file keeps time counting; one warning per unknown episode and a `diagnostic()`; transitions attributed within one poll; cached read within `poll_s`.
- [ ] 3.9 A corrupt `control.json` plus a distress run still crosses at the threshold (mutation-checked by flipping the policy).
- [ ] 3.10 Every welfare caller passes `unknown_counts_as="unfrozen"` (a test inspects the constructed clocks).

## 4. Docs
- [ ] 4.1 The welfare chapter and the caretaker section state that welfare timers count unfrozen time, and why.
