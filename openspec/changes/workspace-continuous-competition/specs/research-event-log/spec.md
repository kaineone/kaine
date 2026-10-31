## ADDED Requirements

### Requirement: Broadcast records carry the pool and access counts
Each workspace broadcast record SHALL carry `n_candidates`, the pool size; `n_accessed`, the number of accessed members; and for each member `held`, whether it was published before the current tick, and `age_s`, entity seconds since its publication. A matched-arm record SHALL carry the content-free `matched_counterfactual`. No field SHALL carry event content.

#### Scenario: A held member
- **WHEN** a broadcast accesses a vision report published 0.4 entity seconds earlier
- **THEN** the record has `n_accessed` 1 and that member has `held` true and `age_s` 0.4

### Requirement: The pool is summarised without content
The cycle SHALL write a content-free pool summary to the research log once per minute of entity time: the pool size distribution, stale and consumed counts per stream, and the number of tick overruns.

#### Scenario: A minute of running
- **WHEN** one entity minute passes
- **THEN** one pool summary record is written and it names streams, never payload fields
