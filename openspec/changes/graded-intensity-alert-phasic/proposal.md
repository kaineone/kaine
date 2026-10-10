## Why

The revised paper (predictive-workspace-paper #21, decisions D2 and R4) settles two rules the code does not yet follow.

- **Graded intensity.** Topos, the acoustic path of Audition, and Chronos report one of two intensities: the alert level when the error ratio (error over its running mean) crosses the alert criterion, the baseline level otherwise. So within a tick the competition ranks module identity, not surprise. Soma and Audition's neutral tone events already grade their intensity by the error ratio. The paper makes that rule uniform: a report that meets its module's alert criterion takes the alert level; any other report takes `I_lo + (I_hi - I_lo) * min(1, ratio / 2)`, reaching the alert level when the error is twice its running mean.
- **Alert-only phasic input.** The access rate's phasic input is the largest intensity among the tick's module reports above a floor of 0.5. With graded intensities Audition's typical report (ratio about 1, intensity about 0.6) sits above the floor, so the rate would almost never rest. The paper counts categorical alerts only: the phasic input is the largest intensity among reports whose payload carries `alert: true`, so with no alert the rate rests at about 3.3 Hz.

## What Changes

- Topos, Audition (acoustic path) and Chronos (when it has a normalised temporal error) compute non-alert intensity with the graded map above, using the same running ratio their alert criterion uses. The z-score fallback Chronos uses before its first temporal error stays two-level.
- Every predictive processor's report payload carries a boolean `alert`: Topos and Audition already do; Soma adds `alert` (a hard-threshold breach); Chronos adds `alert`; Audition's tone events add `alert` (true for a non-neutral tone).
- `max_report_salience` in `kaine/cycle/access_rate.py` counts only events whose payload has `alert` true; its docstring and the module docstring say so.

## Capabilities

### Modified Capabilities

- `syneidesis`: predictive processors report graded intensity.
- `cognitive-cycle`: the access rate's phasic input counts categorical alerts only.

## Impact

- **Code:** `kaine/modules/topos/module.py`, `kaine/modules/audition/module.py`, `kaine/modules/chronos/module.py`, `kaine/modules/soma/module.py`, `kaine/cycle/access_rate.py`.
- **Behaviour:** within a tick, candidates rank by graded surprise within each module's range; the access rate rests unless an alert arrives.
- **Docs:** `docs/08-cognitive-cycle/` and the module pages that describe intensity.
