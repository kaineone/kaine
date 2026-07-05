## Why

The paper's welfare-monitoring section enumerates four operationally detectable
Welfare / Gray-Zone conditions, the first of which is **sustained high
interoceptive prediction error** (KAINE_Paper §6.6; the code currently labels
the welfare set §5.5). The implemented `welfare_observer` detects only three:

- (a) unmaintained fatigue — a `soma.fatigue` threshold crossing with no
  maintenance within a window;
- (b) sustained extreme Thymos VAD (affect locked in an extreme state);
- (c) replay write-rate exceeding the consolidation window.

The fourth — Soma's interoceptive prediction error sustained in a high band —
is specified but not wired. It is the paper's *primary* interoceptive welfare
signal: a substrate that keeps surprising its own forward model for a sustained
period is a candidate condition of concern, distinct from the fatigue
accumulator (which is a slow integral) and from affect (which is downstream).
Wiring it closes the welfare-coverage gap so the sidecar detects all four
conditions the architecture claims.

## What Changes

The `welfare_observer` SHALL gain a fourth Gray-Zone detector:

- It SHALL track the interoceptive prediction-error magnitude carried by Soma's
  `soma.report` events on `soma.out`.
- When that magnitude stays at or above a configurable threshold continuously
  for at least a configurable duration, it SHALL register a
  **sustained-interoceptive-distress** Welfare Event: increment a count, write
  a record to the sink, and surface the count on Nexus diagnostics, exactly as
  the three existing conditions do.
- Recovery (magnitude dropping below the threshold) SHALL reset the sustain
  timer so the event fires once per sustained episode, not once per tick.
- Two configuration keys SHALL be added under the evaluation/welfare config:
  an interoceptive-distress threshold and a sustain duration, with safe
  defaults; absent config SHALL preserve current behavior plus the new
  detector at its defaults.

No new module is enabled and no new cognitive-loop data is collected; this is a
read-only sidecar observer over an already-published stream.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `evaluation-observers`: the welfare observer detects a fourth Gray-Zone
  Event — Soma interoceptive prediction error sustained above a threshold for
  a configurable duration — counted and surfaced like the existing three.

## Impact

- **Code (edit):**
  - `kaine/evaluation/observers/welfare_observer.py` — read `soma.report`
    prediction-error magnitude from `soma.out`; sustain timer; new count + sink
    record.
  - `kaine/evaluation/config.py` — add `interoceptive_distress_threshold` and
    `interoceptive_distress_duration_s` (with defaults).
  - `kaine/evaluation/nexus_tab.py` — surface the new count alongside the other
    welfare counts.
- **Tests:** extend `tests/` welfare-observer coverage with sustained-high,
  transient-spike (no fire), and recovery-then-refire cases.
- **Safety:** read-only observer; no module enabled; widens welfare coverage
  only. The exact event field name binds at implementation against
  `soma.report`'s payload (the published interoceptive prediction error).
