# Welfare timers discount frozen time

## Why
A freeze can be read as distress, as an exhausted warm-up, or as input loss. Every elapsed-time arm of the welfare detectors runs on real wall time and ignores the freeze stack in `state/cycle/control.json`:

- **Sustained distress.** `SustainedThresholdTracker.check_timeout` fires on elapsed time alone, with no new sample (`kaine/lifecycle/welfare_signal.py`; `distress_duration_s = 30` in the protective monitor and the welfare observer). A distress-level sample just before a freeze "sustains" through a freeze of any length.
- **Sustained extreme valence/arousal.** The observer's arm stays set while no `thymos.state` arrives, and that never happens while the cycle is paused.
- **Unmaintained fatigue.** The observer's `maintenance_window_s` counts frozen time.
- **The protective monitor's cold-start warm-up** is used up by frozen time.
- **Input loss.** An operator freeze switches the perception sources off (`kaine/cycle/__main__.py`, freeze watch), so `InputLossWatcher` sees every input go silent and sends a false caretaker "input_lost" notice after `[caretaker].input_loss_after_s`.

The pattern already exists for lived time: `LivedTimeAccumulator` subtracts paused time for the maturation gate and the individuation scheduler. The welfare detectors never adopted it. A freeze must never be read as distress or as quiescence.

## What changes
- **One shared primitive, `UnfrozenClock`** (`kaine/cycle/unfrozen_clock.py`). It is a monotonic wall clock that does not advance while the freeze stack holds any entry, whatever its owner.
  - It reads the freeze state from `control_state`, the same file every freeze owner writes, so it works in the cycle process and in a sidecar process alike.
  - The policy for an unreadable freeze state is an explicit, required argument. Welfare passes `"unfrozen"`, so a broken control file keeps every timer running (fail safe for protection), and the unreadable state is logged and surfaced.
- **Every elapsed-time arm measures unfrozen time:**
  - the sustained-distress tracker in the protective monitor and in the observer;
  - the observer's sustained-extreme-VAD arm;
  - the observer's unmaintained-fatigue window;
  - the monitor's cold-start warm-up;
  - `InputLossWatcher`.
- **Sample-driven behaviour is unchanged:**
  - a sample still crosses or resets a threshold when it arrives, frozen or not;
  - events delivered during a freeze still count in windowed counters;
  - a below-threshold sample during a freeze still resets a sustained run.
- **Real wall time stays where it belongs:**
  - poll cadence;
  - rate limits between preservation attempts;
  - Spot's own heartbeat logic, which already skips freezes it does not own.

## Impact
- Specs:
  - `welfare-monitoring`: elapsed-time arms measure unfrozen time;
  - `unattended-boot`: input loss is measured in unfrozen time.
- Code:
  - new `kaine/cycle/unfrozen_clock.py`;
  - `kaine/cycle/preservation_monitor.py` (protective monitor);
  - `kaine/evaluation/observers/welfare_observer.py`;
  - `kaine/cycle/input_check.py`;
  - their wiring in `kaine/cycle/__main__.py` and the sidecar registry.
- **High-risk** (welfare monitor): Qwen and Kimi first-pass reviews and the integrator's second review.
- **Research impact.**
  - Runs that included an operator freeze, a welfare-protective pause, a Spot recovery freeze, a womb-loss freeze or a programme-end freeze may have logged spurious events: sustained-distress gray-zone events, sustained extreme-VAD events, unmaintained-fatigue events, or caretaker input-loss notices.
  - Read these with care for any interval that overlaps a freeze:
    - the welfare observer's log (`data/evaluation/welfare/`);
    - the protective monitor's `welfare.protective_action` events and incident log;
    - the caretaker notice log.
  - The freeze intervals are recoverable from the cycle log lines and the `runtime.json` freeze fields.
  - No running study is affected, because studies are paused.
