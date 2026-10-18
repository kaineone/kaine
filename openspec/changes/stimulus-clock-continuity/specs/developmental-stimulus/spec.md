## ADDED Requirements

### Requirement: The stimulus source clock continues across restarts
The stimulus source clock SHALL resume each boot from its own elapsed time, persisted in the stage file as `stimulus_source_seconds`, so a restart neither repeats nor skips stimulus the entity has had. The gate runner SHALL record the clock's reading on every gate tick, sleep included, and on its final write at shutdown. Time while the process is stopped SHALL NOT advance the stimulus clock. A stage file without `stimulus_source_seconds` SHALL fall back to the awake-time offset. The colour schedule and the voice repertoire SHALL keep following awake time.

#### Scenario: A plain restart after sleep
- **WHEN** a developing entity has 3600 s of stimulus time and 3500 s of awake time, the difference spent asleep, and it shuts down cleanly and restarts
- **THEN** the stimulus source clock resumes at 3600 s, not 3500 s

#### Scenario: Downtime does not advance the mother
- **WHEN** the process is stopped for 12 hours between two boots
- **THEN** the stimulus source clock resumes at the time recorded at shutdown

#### Scenario: A stage from before this change
- **WHEN** the stage file has `lived_seconds` but no `stimulus_source_seconds`
- **THEN** the stimulus source clock resumes at `lived_seconds`, as before
