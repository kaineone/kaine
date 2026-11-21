# Adversarial science review — deprivation-waits-for-next-stage

Reviewer: lead (Claude), 2026-11-20, at the operator's request. Every claim below was checked against the code on `main`.

## Findings

### R1 D1 must cover boredom only (design changed)

A hearing step relieves only boredom. Boredom is relieved continuously by learning progress and by engagement (`config/kaine.toml`, `[affect.drives.boredom]`), and audition's learning progress restarts at a step. The social drive is relieved only when the time since the last interaction falls (`kaine/modules/affect/module.py:1594`), and restlessness only by the entity's own non-rest intents (`:1632`). Waiting for a step would delay the response to social or restlessness deprivation and offer them no relief. D1 now covers `boredom_deprived` only; the other deprivation indicators keep today's response.

### R2 The uncontrolled indicator is neither a threat to D1 nor its backstop (D5 resolved)

`WelfareIndicatorEvaluator.restart()` (`kaine/lifecycle/welfare_indicators.py:392`) clears every drive's end record and sets `_last_ends` to `None`, so the first `affect.state` after a rest only re-baselines the end counters. A rest's end is never counted. Under a spent stimulus, boredom crosses once in a fresh span and stays over its bar with no end, so `n = 1` and the posterior is 1/2, under `q_wf`. The draft's D5 concern (four net rests make boredom uncontrolled) does not occur. It follows that D3's bound is the only limit on the wait, so D3 is load-bearing and its test (task 2.3) must be a mutation-checked test.

### R3 Caretaker notices need aggregating (design changed)

Under a spent stimulus a boredom crossing comes about 600 awake seconds after each rest (the span must hold `Δ_stall` before it is evaluated). The cycle is then about 600 s awake and 1410 s resting, so a raw notice per crossing means a notice about every 34 minutes for up to seven awake hours. CAL Article 4.7 requires every crossing to be flagged for review, and the record still flags each one. The caretaker gets one notice when the wait starts, one at each hearing step, and one on escalation.

### R4 Rest share while waiting

About 70 % of the time is rest (1410 of every ~2010 s). Late in prenatal development, fetuses spend most of their time in quiet and active sleep (Nijhuis et al. 1982), so a mostly resting entity between hearing steps fits the developmental model. Accepted.

### R5 D0 hypotheses

- Ruled out: affect missing the stage-0 `development.hearing_stage` event at boot. `_phase_registry` initializes the modules, and affect sets its cursors to the stream tail, before `_phase_development` starts the hearing watch, which publishes stage 0 on its first check.
- Open and most likely: audition's learning-progress window returning `None` (no audition window with a value), which `HearingStageState.observe` counts as unsaturated, holding a stage to `max_dwell_seconds`. Boredom building while the stage never saturates is otherwise hard to explain, since both follow low learning progress. Task 1.1 checks the archives.

### R6 Timing correction

The worker suggested that D3's bound (`max_dwell_seconds` + 2996 s) falls before the observed freezes. It compared awake with wall time. With 2996 s awake per 1410 s rest, an 8 h 20 min wall-clock freeze is about 5 h 40 min awake, inside a stage's 7 h maximum. D3's bound comes at about 7 h 50 min awake, about 11 h 30 min wall time.

### R7 `rest_failed` is out of scope but unexplained

9 of 34 freezes were `indicator_rest_failed`: a rest that did not start or complete in its bound. This change does not touch that path. Task 1.1 records which bound each one hit, as a separate finding.

### R8 Paper

The change departs from paper §6.5 (a second crossing over a fresh span preserves and freezes). Task 0.3 queues the revision for the operator's paper review.

## Verdict

Sound with R1 and R3 applied. D3 is the only bound on the wait (R2), so it gets a mutation-checked test. D0 still comes first.
