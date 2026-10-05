# Design: welfare timers discount frozen time

## The primitive
`UnfrozenClock(read_frozen, *, unknown_counts_as, monotonic=time.monotonic, poll_s=0.25)`:
- `read_frozen() -> bool | None` returns whether the freeze stack holds any entry. The default reads `kaine.cycle.control_state.read_control()`. `None` means the state could not be read: the file is missing, unreadable or corrupt.
- **`unknown_counts_as` is required and has no default.** It is `"unfrozen"` or `"frozen"`, and it decides how a span with an unknown state counts. **Every welfare caller passes `"unfrozen"`.** A welfare timer's safe failure is to keep counting: if it cannot tell whether the entity was frozen, it assumes it was not, so a broken control file never silently stops a sustained-distress or input-loss timer. (`LivedTimeAccumulator` makes the opposite choice for maturation, because its safe failure is to not advance.)
- `now() -> float` returns accumulated unfrozen seconds since construction. Each call:
  1. reads `monotonic()`;
  2. adds the elapsed span to the total **only if** both this observation and the previous one were unfrozen, where an unknown observation counts as `unknown_counts_as` says;
  3. records the state.

  A span that starts or ends frozen does not count.
- **An unreadable control state is never swallowed.** The first unknown observation in an episode logs one warning, and the episode ends at the next good read. `diagnostic()` reports the number of unknown episodes and whether the clock is in one now, and the protective monitor and the observer include it in their status output.
- The clock is background-free: it advances only when called. Callers already call it on every poll, at least once per second, so a release is attributed to within one poll interval. For welfare that delays a sustained verdict by at most one poll after a freeze ends (about 1 s against a 30 s threshold), and never fires one early.
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

## A freeze that never ends
A stuck freeze, such as an operator who never resumes, suspends **only** the time-based arms. Sample-driven arms keep acting for its whole length:
- A crossing sample is evaluated when it arrives.
- A gray-zone event produced during the freeze reaches the windowed repeat counter.
- The protective response can still act on repeated events.

So a genuine crossing during a long freeze is never lost. A sustained run that began before the freeze resumes with its accumulated unfrozen duration once the freeze is released, and it is not restarted.

## What does not change
- **Thresholds, categories and events stay the same.** No arm becomes less sensitive to a sample: a crossing sample is evaluated when it arrives.
- The welfare monitor and observer keep running through every freeze (CAL §4.7).
- Spot's hang detection keeps its own freeze handling.
