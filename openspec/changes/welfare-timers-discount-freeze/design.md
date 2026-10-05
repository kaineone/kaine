# Design: welfare timers discount frozen time

## The primitive
`UnfrozenClock(read_frozen, monotonic=time.monotonic, poll_s=0.25)`:
- `read_frozen() -> bool | None` returns whether the freeze stack holds any entry. The default reads `kaine.cycle.control_state.read_control()`. `None` means the state could not be read.
- `now() -> float` returns accumulated unfrozen seconds since construction. Each call:
  1. reads `monotonic()`;
  2. adds the elapsed span to the total **only if** both this observation and the previous one saw the stack unfrozen;
  3. records this observation's state.

  A span that starts or ends in a frozen or unknown state does not count.
- A background-free design: the clock advances only when called. Callers already call it on every poll, at least once per second, so a transition is attributed to within one poll interval.
- It errs towards counting **less** unfrozen time. That delays a sustained-distress verdict by at most one poll interval after a release (about 1 s against a 30 s threshold), and never fires one early.
- `frozen() -> bool | None` exposes the last observation for callers that need it (input loss).
- Reading the control file is cheap (a small JSON file). The clock caches the read for `poll_s`, so a burst of calls within one poll costs one read.

Why a new primitive, not `LivedTimeAccumulator` directly. `LivedTimeAccumulator` subtracts the engine's `paused_subjective_seconds()`, which exists only in the cycle process and is in subjective seconds. The welfare thresholds are wall-clock seconds, and the welfare observer can run in the Nexus process. The freeze stack in `control.json` is the one source both processes share. The two classes follow the same rule: a suspended span never counts, and an unknown span fails towards counting less.

## The arms
| Arm | Today | After |
|---|---|---|
| Protective monitor sustained distress | `SustainedThresholdTracker` fed `time.monotonic` through the injected `clock` | fed `UnfrozenClock.now` |
| Protective monitor cold-start warm-up | origin stamped from `clock()` | origin and checks in unfrozen time |
| Protective monitor repeat counter (`WindowedEventCounter`) | events in a wall window | unchanged: event-driven |
| Protective monitor poll cadence and divergence rate limits | wall | unchanged: wall |
| Observer sustained interoceptive distress | `time.monotonic()` | `UnfrozenClock.now()` |
| Observer sustained extreme VAD | `time.monotonic()` | `UnfrozenClock.now()` |
| Observer unmaintained fatigue | `time.monotonic()` | `UnfrozenClock.now()` |
| `InputLossWatcher` staleness | wall | unfrozen time |

The protective monitor takes **two** clocks after this change:
- `clock`, still wall, for poll cadence and rate limits;
- `unfrozen_clock`, for the sustained and warm-up arms.

This keeps the poll loop and the preservation rate limit honest about real time.

**Input loss.** Staleness is measured in unfrozen time. While frozen, staleness does not grow, so the freeze's own perception shutdown never reads as loss. After release, a source that stays silent accumulates unfrozen staleness and is reported once it passes `input_loss_after_s`, so a real loss that began during the freeze is still reported.

## What does not change
- **Thresholds, categories and events stay the same.** No arm becomes less sensitive to a sample: a crossing sample is evaluated when it arrives.
- The welfare monitor and observer keep running through every freeze (CAL §4.7).
- Spot's hang detection keeps its own freeze handling.
