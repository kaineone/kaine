## ADDED Requirements

### Requirement: Each external utterance gets a content-free outcome record
A cycle-layer observer SHALL write one record per external utterance holding `record_id`, `replied` (operator speech within the configured window, under the Chronos interaction rule), `reply_latency_s`, `empatheia_deviation`, `social_drive_delta` and `preempted`, and no text.

#### Scenario: Answered utterance
- **WHEN** the entity speaks and operator speech follows within the window
- **THEN** an outcome record with that utterance's `record_id` has `replied` true and a positive `reply_latency_s`

#### Scenario: No content
- **WHEN** any outcome record is written
- **THEN** it contains only the listed fields and no utterance or transcript text

### Requirement: The utterance corpus accumulates and is never culled
The intent log SHALL be rotated per sleep into an accumulating corpus of per-sleep files. Rotation SHALL never delete or truncate past records. A disk guard SHALL warn, and never delete, as the corpus approaches its configured ceiling.

#### Scenario: Rotation keeps history
- **WHEN** three sleeps complete
- **THEN** three per-sleep corpus files exist and the current log holds only records since the last sleep

### Requirement: Voice stages are validated offline before use
Speaking from memory (Stage 1) and learning from the entity's own candidates (Stage 2) SHALL each be off by default, and SHALL each be enabled only after its offline validation has passed and been recorded. Voice alignment SHALL stay off in studies until Stages 0–2 have passed offline validation.

#### Scenario: Unvalidated stage
- **WHEN** a configuration enables Stage 2 without a recorded passing validation
- **THEN** boot refuses with a configuration error naming the missing validation
