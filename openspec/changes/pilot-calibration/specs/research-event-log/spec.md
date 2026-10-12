## ADDED Requirements

### Requirement: Reports carry entity time and wakefulness
The vision module (`topos.report`), the audition module (`audition.perception`) and the interoception module (`soma.report`) SHALL put on every report `entity_time_s`, the entity clock's reading for the report (entity seconds since the run started), and `awake`, false while the sleep module holds the processor asleep, and the curated research log SHALL copy both. The planned test counts a report only when the entity was awake and the report falls after the learning period T_learn, measured in entity time from the start of the run (paper Appendix A.8). The range sweep SHALL bound `entity_time_s` below by 0.

#### Scenario: A report while asleep
- **WHEN** the vision module reports after a sleep has started
- **THEN** the report carries `awake` false and the entity clock's reading in `entity_time_s`

### Requirement: The research log records the positive control's ladder and settings
The curated research log SHALL copy from `positive_control.result` also `mode`, `t_learn_s`, `settings_sha256` and `pc_sha256`, and from each `positive_control.ladder` event only `processor`, `entity_time_s`, `gain`, `gain_with`, `gain_noise`, `snr` and `pc_sha256`.

#### Scenario: A ladder record is logged
- **WHEN** a ladder event carries an extra field
- **THEN** the research record has every ladder field and not the extra one

### Requirement: Broadcasts record the coalition capacity
Competitive and matched broadcast snapshots, including empty ones, SHALL carry `coalition_capacity` (the coalition size K) in their metadata, and the research log's `workspace.broadcast` record SHALL copy it, so a run in which the on arm never had more candidates than K can be classified NOT EXERCISED from the log.

#### Scenario: An empty competitive broadcast
- **WHEN** the competitive arm selects from no candidates
- **THEN** the snapshot's metadata carries `coalition_capacity` equal to `top_k`
