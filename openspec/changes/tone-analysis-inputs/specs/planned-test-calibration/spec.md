## ADDED Requirements

### Requirement: The tone analysis
The tone analysis SHALL read a run's research log, take the classified `audition.emotion` events of the tone variant, mark each as accessed content or not from the broadcast records, and compute the run-level statistic: the fraction of emotional (non-neutral) tone events that are accessed content minus the fraction of neutral ones, undefined when the run has no emotional or no neutral tone event. Across runs it SHALL apply the sign tests of the decision rule (paper A.8) to the statistic minus the minimum effect: exact zeros dropped, WIN when the WIN test's p-value is at most 0.05, NEGATIVE when the NEGATIVE test's is, NOT EXERCISED when no run has a defined statistic, and NULL otherwise.

#### Scenario: Emotional tone accessed more often
- **WHEN** ten runs each have an accessed fraction of emotional tone events 0.3 above that of neutral ones and the minimum effect is 0.1
- **THEN** the verdict is WIN

### Requirement: Tone-variant pilot runs and the tone minimum effect
The calibration tool SHALL accept in each pilot of the plan a `tone` run beside the three arms, or none in every pilot. A tone run SHALL have the study `workspace_mediation_pilot_tone`, share its pilot's seed and film program, carry competitive broadcasts and tone events with `tone_rule` `error_ratio`. The minimum effect of the tone analysis SHALL be c_eff times the sample standard deviation of the run-level statistic over the tone runs of the counted pilots, leaving out runs in which it is undefined; it SHALL be blocked when the plan has no tone runs or fewer than two statistics are defined. The tone bins SHALL stay blocked until the operator settles which pilot runs' tone events they are taken over. A record is complete only with tone runs in every pilot and both tone settings.

#### Scenario: A plan without tone runs
- **WHEN** the plan's pilots name only the three arms
- **THEN** the record is written with `min_effect_tone` null and blocked, and the record is incomplete
