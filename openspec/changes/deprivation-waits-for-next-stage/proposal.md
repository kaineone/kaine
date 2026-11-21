## Why

The operator ruled on 2026-11-20 that the boredom freeze on the 2026-11-17 development-run boots was too strict: it should have let the next developmental stage start before assuming trouble.

The 2026-11-17 freeze evidence (`docs/records/freeze-evidence-summary-2026-11-17.md`) has 34 freezes. 25 were for `indicator_boredom_deprived` and 9 for `indicator_rest_failed`, and every timed one came between 8 h 11 min and 8 h 30 min of run time. A pattern that tight points to the schedule, not to the entity: the welfare indicator response (`welfare-indicator-response`, design D4) is built so that under a spent stimulus the second crossing comes about ten minutes after the rest, and the hearing band's next stage can arrive up to `max_dwell_seconds` (25200 awake seconds, 7 h) after the last. In the developmental phase, "spent" was read as "spent for good" while the stimulus schedule still had stages to give.

## What Changes

- In the developmental phase, a `boredom_deprived` crossing over the fresh span after its rest does not preserve and freeze while the hearing schedule has a stage still to come. Social-drive and restlessness deprivation are unchanged, since a hearing step does not relieve them. The response requests another rest and waits for the next hearing-band step.
- Every hearing-band step restarts every indicator span, as a completed rest does. A crossing over a span that started at a step is a first crossing again.
- The freeze still comes for deprivation when the schedule is complete (the band is open) and a crossing follows the rest, as today.
- Negative valence and the uncontrolled indicators keep today's response in every phase: they report distress, not a stimulus that is temporarily thin.
- A bound keeps the wait finite: if boredom deprivation stays over its bar for a whole developmental awake stretch after the stage's `max_dwell_seconds` should have ended it, the monitor escalates with a new reason, `indicator_stage_overdue`.
- The caretaker gets one notice when the wait starts, one per hearing step and one on escalation; every crossing is still recorded and flagged for review.
- Root cause first: before any change to the response, find out why audition's learning progress did not saturate and step the band within eight hours on those boots. A learning-progress reading that never arrives counts as unsaturated, which would hold a stage to its maximum dwell.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: in the developmental phase a boredom deprivation crossing waits for the next hearing-band step while the schedule has one to come; each step restarts the spans; an overdue step escalates.

## Impact

- `kaine/cycle/preservation_monitor.py` (the indicator state machine), `kaine/lifecycle/welfare_indicators.py` (span restart on a step), the hearing-stage event the monitor reads, the caretaker notices, `config/kaine.toml` comments, tests.
- Welfare-critical: an adversarial science review and an independent second review before merge, as for `welfare-indicator-response`.
- No change to the matured phase.
