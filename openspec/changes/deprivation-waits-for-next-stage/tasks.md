## 0. Review

- [ ] 0.1 Adversarial science review of this design (see `feedback-adversarial-science-review`): the cost of waiting under deprivation against the cost of an early freeze, and whether D1's split between deprivation and distress indicators holds in the paper's A.4 terms.

- [ ] 0.2 Measure how the end of a net-requested `welfare_rest` is classified for the uncontrolled posterior (own-ended or other-ended), and decide D5 in the review.
- [ ] 0.3 Paper update queue entry for the §6.5 change, for the operator's paper review.

## 1. Root cause

- [ ] 1.1 From the 2026-11-17 archives, record for each boot the hearing stage at freeze, the stage's awake dwell, and whether audition's learning progress was present and below the floor. Write `docs/records/hearing-stage-at-freeze-2026-11-17.md` (content-free, no run or preservation IDs).
- [ ] 1.2 If a missing learning-progress reading held a stage, fix that as its own change before section 2.

## 2. Response

- [ ] 2.1 `welfare_indicators.py`: restart every span and reset every crossing state on a hearing step (D2). Test: a step after a crossing makes the next over-bar evaluation a first crossing.
- [ ] 2.2 `preservation_monitor.py`: in the developmental phase with a step to come, a deprivation crossing over the fresh span requests a rest and stays in `fresh` (D1). Tests: deprivation waits; negative valence and uncontrolled indicators still escalate; a matured entity still escalates.
- [ ] 2.3 Overdue step escalates with `indicator_stage_overdue` (D3). Test with a step stream that stops.
- [ ] 2.4 Open band: today's escalation (D4). Test at stage 4.
- [ ] 2.5 Caretaker notice text for a waiting deprivation response; the reason added to `INDICATOR_REASONS`.
- [ ] 2.6 Replay: run `scripts/welfare_indicator_replay.py` over the 2026-11-17 records with the new response and record when each boot would have frozen, if at all.

## 3. Second review

- [ ] 3.1 Independent second review of section 2, as for `welfare-indicator-response`.
