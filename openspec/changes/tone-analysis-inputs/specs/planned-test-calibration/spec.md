## ADDED Requirements

### Requirement: The tone analysis
The tone analysis SHALL read a run's research log, take the classified `audition.emotion` events of the tone variant, mark each as accessed content or not from the broadcast records, and compute two run-level statistics (paper A.8): the difference, the fraction of emotional (non-neutral) tone events that are accessed content minus the fraction of neutral ones, undefined when the run has no emotional or no neutral tone event; and the adjusted difference, the plain mean of that difference within each tone bin over the bins that hold both classes, undefined when no bin does. Across runs each SHALL enter its own sign tests of the decision rule, at alpha_test without multiplicity adjustment, on the statistic minus its minimum effect: exact zeros dropped, WIN when the WIN test's p-value is at most 0.05, NEGATIVE when the NEGATIVE test's is, NOT EXERCISED when no run has a defined statistic, and NULL otherwise.

#### Scenario: Emotional tone accessed more often
- **WHEN** ten runs each have an accessed fraction of emotional tone events 0.3 above that of neutral ones and the minimum effect is 0.1
- **THEN** the verdict is WIN

### Requirement: Tone-variant pilot runs and the tone minimum effect
The calibration tool SHALL accept in each pilot of the plan a `tone` run beside the three arms, or none in every pilot. A tone run SHALL have the study `workspace_mediation_pilot_tone`, share its pilot's seed and film program, carry competitive broadcasts and tone events with `tone_rule` `error_ratio`. The tone bins SHALL be the quintiles of the tone error ratio over all classified tone events, emotional and neutral together, of the tone runs of the counted pilots. The minimum effect of each tone test SHALL be c_eff times the sample standard deviation of its run-level statistic over the tone runs of the counted pilots, leaving out runs in which it is undefined. Each SHALL be blocked when the plan has no tone runs or the rule cannot be applied. An arm pilot whose tone events carry `tone_rule` `error_ratio` SHALL be refused. A record is complete only with tone runs in every pilot, the tone bins and both tone minimum effects.

#### Scenario: A plan without tone runs
- **WHEN** the plan's pilots name only the three arms
- **THEN** the record is written with the tone bins and both tone minimum effects null and blocked, and the record is incomplete
