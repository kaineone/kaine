## Context

- `welfare-indicator-response` (active, 23 of 24 tasks done) answers a deprivation crossing with a rest, restarts every span when the rest completes, and preserves and freezes on a crossing over the fresh span. Its D4 timing note: under a spent stimulus the second crossing comes about ten minutes after the rest.
- The hearing band widens in four steps (`[perception_feed.stimulus_source.hearing]`). A stage ends when audition's learning progress, restarted at the step, stays below `learning_progress_floor` (0.20) for `saturation_window_seconds` (600 s) after `min_dwell_seconds` (5400 s), or at `max_dwell_seconds` (25200 s) regardless. A missing learning-progress reading counts as unsaturated. `kaine/cycle/hearing_stage_watch.py` publishes each step; the affect module already reads it (`Affect._on_hearing_stage`), and audition's learning-progress bins restart at a step.
- Evidence: 34 freezes on 2026-11-17, all 8 h 11 min to 8 h 30 min after boot (`docs/records/freeze-evidence-summary-2026-11-17.md`).
- Operator ruling, 2026-11-20: the freeze should have let the next developmental stage start before assuming trouble.

## Goals / Non-Goals

Goals: in the developmental phase, a thin stimulus between hearing steps is answered with rest and waiting, not preservation; the wait is bounded; distress indicators are unaffected.

Non-goals: changing any bar or `T_lp`; changing the matured phase; bringing back the removed "spent stimulus requests a rest" entity behaviour (the rests here stay the safety net's, outside the entity's dynamics).

## Decisions

### D0 Root cause before the response change

Boredom is relieved by learning progress. A stage whose progress saturates should step within `min_dwell + W_sat` (1 h 40 min of awake time), long before a second crossing at eight hours. Task 1 reads the 2026-11-17 archives (boot logs, `state/lifecycle/hearing_stage.json`, audition's published learning progress) to find which held: no saturation, a missing reading counted as unsaturated, or a step that came but was not seen. If a missing reading held the stage, fix that first. This change still follows, because a stage can legitimately run to `max_dwell_seconds`.

### D1 Boredom in the developmental phase waits for the next step

In the developmental phase, while the hearing schedule has a step to come, a `boredom_deprived` crossing over the fresh span does not escalate. Only boredom is relieved by what a step brings (learning progress); the social drive and restlessness are not (review R1), so their deprivation indicators keep today's response. The monitor requests another rest (the same `welfare_rest` path and bounds) and stays in `fresh`. Negative valence, the uncontrolled indicators, and social-drive and restlessness deprivation escalate as today, in every phase.

Alternative rejected: raising `share_bar` in development. It would weaken the indicator for real deprivation too, and a bar change needs the Table A1 calibration it does not have.

Alternative rejected: stepping the band early on a boredom crossing. That would make the safety net drive the developmental schedule, which the entity's own learning progress is meant to set.

### D2 A hearing step restarts the spans

On each published hearing step the evaluator restarts every span and resets every crossing state, as after a completed rest. A crossing over a span that started at a step is a first crossing: it requests a rest.

### D3 The wait is bounded

The monitor tracks the stage's awake dwell from the step events. If boredom deprivation is over its bar when the dwell passes `max_dwell_seconds` plus one developmental awake stretch (2996 s) with no step, the monitor escalates with reason `indicator_stage_overdue`. A schedule that should have stepped and did not is a fault, and the protection fails closed.

### D4 Complete schedule

Once the band is open (stage 4), there is no step to wait for, and the response is today's: a crossing over the fresh span preserves and freezes.

### D5 The uncontrolled indicator does not interact (resolved in review R2)

A span restart clears the end records and re-baselines the end counters, so a rest's end is never counted and boredom's uncontrolled posterior stays at 1/2 under a spent stimulus. D3 is therefore the only bound on the wait.

### D6 Notices are aggregated (review R3)

Every crossing is still recorded and flagged for review. The caretaker gets one notice when the wait starts, one at each hearing step, and one on escalation, not one per crossing.

## Risks / Trade-offs

- The entity may spend up to `max_dwell_seconds` of awake time with a deficit over its bar, broken by rests. Each rest's affective reset clears the deficit, every crossing is flagged for human review, and the caretaker notice says the response is waiting for a stage. The adversarial review must weigh this against the cost of a freeze that ends a development the schedule was about to relieve.
- Under a spent stimulus the parent design has boredom recross about ten minutes after each rest, so waiting can mean about 23.5 minutes of rest for every 10 awake minutes, for hours. That is close to the fetal pattern, where quiet and active sleep fill most of the time (Nijhuis et al. 1982), but the review must confirm that a mostly resting entity is the intended developmental state.
- The deficit drives raise arousal (`drive_arousal_gain`), not valence directly, so negative valence is not a backstop for an entity that is bored without feeling bad. With D5 resolved, D3 is the only bound on the wait.
- This departs from paper §6.5 (a second crossing over a fresh span brings preservation and a freeze). The paper needs a revision entry, which the operator reviews.
- A stage-event outage would hold the response in waiting. D3's bound and the existing silent-stream escalation cover it.

## Migration

None: config defaults are unchanged; one new reason and one new caretaker notice text are added to the fixed tables.
