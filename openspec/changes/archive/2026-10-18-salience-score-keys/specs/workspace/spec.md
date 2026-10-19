## ADDED Requirements

### Requirement: The score table has one key per candidate
Every candidate of a tick SHALL have an id unique within the tick's batch, and the cycle SHALL form it as `<stream>:<entry_id>` from the stream the candidate was read from and its bus entry id, because a bus entry id is unique only within its stream. The snapshot's `salience_scores` SHALL hold exactly one entry per candidate under that id, and each coalition member's id in `selected_events` and in the broadcast payload SHALL be the same id, in the competitive, matched and pooled arms and in both snapshots of the dual-path selection. The workspace SHALL refuse a candidate list in which two candidates share an id. A record written before this change keys its table by bare entry ids; a reader SHALL look up a member's score with the member's own id, which has the same form as the table's keys in the same record.

#### Scenario: Two streams publish the same entry id
- **WHEN** `interoception.out` and `vision.out` each hold an entry with id `1760000000000-0` and the cycle reads both on a broadcast tick
- **THEN** the broadcast's score table has two entries, `interoception.out:1760000000000-0` and `vision.out:1760000000000-0`, and each member's score under its own id is its own score

#### Scenario: Every arm keys members and scores alike
- **WHEN** a tick's candidates come from two streams that share an entry id, in the competitive, matched or pooled arm
- **THEN** the score table has one entry per candidate and every coalition member's id is a key of the table

#### Scenario: Duplicate candidate ids are refused
- **WHEN** `select` is given two candidates with the same id
- **THEN** it raises `ValueError`

#### Scenario: A bare legacy key is recognised
- **WHEN** `split_stream_entry_key` is given `1760000000000-0`
- **THEN** it returns `(None, "1760000000000-0")`
