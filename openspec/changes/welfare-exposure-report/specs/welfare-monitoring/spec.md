## ADDED Requirements

### Requirement: Every research run ends with a welfare exposure record
At shutdown a research-mode cycle SHALL write `state/welfare/exposure.json` as plain JSON, atomically and with mode 0600, carrying `run_id`, `boot_started_at`, the welfare monitor's per-indicator largest value, crossings, rests requested and freezes placed, and the producer tally's shares with `producer_restarts` and `covered_awake_seconds`. It SHALL hold numbers, booleans and fixed labels only. A failed write SHALL be logged at error level.

#### Scenario: A boot with one rest
- **WHEN** a research run's boredom indicator crossed once and the requested rest was followed by no second crossing
- **THEN** the exposure record shows one boredom crossing, one rest requested and no freeze, with this run's `run_id`

#### Scenario: The record is content-free
- **WHEN** the record is written
- **THEN** every value is a number, a boolean, the run id, a timestamp or a label from the fixed indicator and drive tables

#### Scenario: A restarted producer
- **WHEN** the welfare producer was restarted once during the run
- **THEN** the record's indicator figures cover the whole run, and `producer_restarts` is 1 with `covered_awake_seconds` below the run's awake seconds

### Requirement: The exposure coverage is compared in one unit
The exposure record SHALL carry the welfare monitor's awake time in entity seconds (`awake_seconds`) and in wall seconds (`awake_wall_seconds`, null when the time scale could not be read). The study runner SHALL compare the tally's `covered_awake_seconds`, which counts wall seconds, against `awake_wall_seconds`, and SHALL hold for incomplete coverage when that field is missing or not a number.

#### Scenario: A dilated clean boot
- **WHEN** a clean boot runs at time scale 2 for 900 wall seconds
- **THEN** `awake_seconds` is about 1800, `awake_wall_seconds` and `covered_awake_seconds` are about 900, and the runner does not hold

#### Scenario: An unreadable time scale
- **WHEN** the time scale cannot be read while awake time accrues
- **THEN** `awake_wall_seconds` is null and the runner holds for incomplete coverage

### Requirement: A stale exposure record is removed at boot
Every cycle boot SHALL delete any existing `state/welfare/exposure.json` before the boot gates run.

#### Scenario: A revive from a bundle that holds an old record
- **WHEN** a step revives a bundle whose state contains an exposure record and then crashes before shutdown
- **THEN** no exposure record exists after the crash
