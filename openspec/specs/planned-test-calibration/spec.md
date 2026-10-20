# planned-test-calibration Specification

## Purpose
TBD - created by archiving change tone-analysis-inputs. Update Purpose after archive.

## Requirements

### Requirement: The tone analysis
The tone analysis SHALL read a run's research log, take the classified `audition.emotion` events of the tone variant whose `entity_time_s` is after the learning period T_learn (paper A.8), refusing a tone event without a finite `entity_time_s`, mark each as accessed content or not from the broadcast records, and compute two run-level statistics (paper A.8): the difference, the fraction of emotional (non-neutral) tone events that are accessed content minus the fraction of neutral ones, undefined when the run has no emotional or no neutral tone event; and the adjusted difference, the plain mean of that difference within each tone bin over the bins that hold both classes, undefined when no bin does. Across runs each SHALL enter its own sign tests of the decision rule, at alpha_test without multiplicity adjustment, on the statistic minus its minimum effect: exact zeros dropped, WIN when the WIN test's p-value is at most 0.05, NEGATIVE when the NEGATIVE test's is, NOT EXERCISED when no run has a defined statistic, and NULL otherwise.

#### Scenario: Emotional tone accessed more often
- **WHEN** ten runs each have an accessed fraction of emotional tone events 0.3 above that of neutral ones and the minimum effect is 0.1
- **THEN** the verdict is WIN

#### Scenario: Tone events before T_learn
- **WHEN** a run's tone events before T_learn would change its difference
- **THEN** the difference equals the one computed from the events after T_learn alone

### Requirement: Tone-variant pilot runs and the tone minimum effect
The calibration tool SHALL accept in each pilot of the plan a `tone` run beside the three arms, or none in every pilot. A tone run SHALL have the study `workspace_mediation_pilot_tone`, share its pilot's seed and film program, carry competitive broadcasts and tone events with `tone_rule` `error_ratio`. The tone bins SHALL be the quintiles of the tone error ratio over all classified tone events after T_learn, emotional and neutral together, of the tone runs of the counted pilots, and the tone statistics SHALL count only those events. The minimum effect of each tone test SHALL be c_eff times the sample standard deviation of its run-level statistic over the tone runs of the counted pilots, leaving out runs in which it is undefined. Each SHALL be blocked when the plan has no tone runs, T_learn is not known, or the rule cannot be applied. An arm pilot whose tone events carry `tone_rule` `error_ratio` SHALL be refused. A record is complete only with tone runs in every pilot, the tone bins and both tone minimum effects.

#### Scenario: A plan without tone runs
- **WHEN** the plan's pilots name only the three arms
- **THEN** the record is written with the tone bins and both tone minimum effects null and blocked, and the record is incomplete

### Requirement: The tone analysis joins on stream-qualified ids
The tone analysis SHALL join a tone event to a broadcast member on source, type and the stream-qualified id `<stream>:<entry_id>`, and SHALL refuse with `ToneAnalysisError` a tone event or broadcast member whose id has no stream. It SHALL refuse a broadcast whose members share an id.

#### Scenario: A tone event accessed through the cycle is found
- **WHEN** a tone event and an interoception event with the same bus id on their own streams are read on one broadcast tick, the tone event's score reaches the threshold and the interoception event's does not
- **THEN** the tone analysis finds the tone event accessed

#### Scenario: A bare id is refused
- **WHEN** a tone record's `entry_id` is `0-0`
- **THEN** `tone_events` raises `ToneAnalysisError`

### Requirement: Robust bias-corrected regression discontinuity, written from the paper
`kaine/experiment/rd_robust.py` SHALL implement, from Calonico, Cattaneo and Titiunik (2014) and its Supplemental Material only, the local-linear estimate of the jump at the cutoff with the triangular kernel, its local-quadratic bias correction, the conventional and robust standard errors with nearest-neighbor or plug-in-residual variance, a run-clustered variance, the robust confidence interval, and the MSE-optimal bandwidths of Supplement S.2.6. It SHALL take no dependency on the authors' software.

#### Scenario: A linear outcome with a jump
- **WHEN** the outcome is a linear function of the running variable plus a jump of 0.5 at the cutoff
- **THEN** the conventional and bias-corrected estimates equal 0.5 for any bandwidths

### Requirement: The contrast at threshold and its settings
The calibration tool SHALL compute theta_band and b_band on the pooled on-arm pilot broadcasts that have a following included report (one observation each, the mean gain of those reports), the age bins as quintiles of the context age over the included reports that follow broadcasts within theta_band of the threshold, and the contrast's minimum effect as c_eff times the sample SD of the run contrast over the counted pilots, leaving out undefined ones. A side of a bin SHALL count as fittable only when it holds at least 10 distinct scores within theta_band and within b_band and each weighted least-squares problem, with the score scaled by its bandwidth, has a condition number of at most 10^8. The run contrast SHALL be the mean, over the age bins whose two sides can be fitted, of the bias-corrected jump of the per-broadcast mean gain at S*_k = theta, with bandwidths theta_band and b_band. The analysis SHALL report, for each bin, the robust interval of the estimate pooled over runs with standard errors clustered by run (the joint Liang-Zeger sandwich with the CR1 factor G/(G-1)(N-1)/(N-K), K = 6 for the robust variance), and the verdict of the decision rule's sign tests on the run contrasts.

#### Scenario: Complete pilot data
- **WHEN** the plan has counted pilots with tone runs and on-arm logs that record the preceding broadcast of each report
- **THEN** the settings record has no blocked value and is complete
