## ADDED Requirements

### Requirement: The welfare board shows the affect welfare record
The health snapshot's `welfare` block SHALL carry `affect_welfare`: the newest `affect_welfare` record in the welfare rollup, holding only its timestamp and these numeric measures (each a finite number or null): `awake_seconds`, `negative_valence_bar`, `negative_valence_share`, and for each of `boredom`, `social_drive` and `restlessness` the `_uncontrolled_share`, `_uncontrolled_per_awake_hour`, `_deprivation_share`, `_sleep_reset_ends` and `_open_crossings` measures, and `curiosity_interest_share`, together with `current_run`, true when no observer start follows the record in the rollup. Any other field SHALL be dropped. With no record the value SHALL be null. The welfare board SHALL show the measures per drive, the record's time, and a note when the record predates the observer's latest start.

#### Scenario: A record since the latest start
- **WHEN** the rollup's newest affect welfare record follows its latest reset advisory
- **THEN** the panel shows its measures per drive and `current_run` is true

#### Scenario: Only an older record
- **WHEN** a reset advisory follows the newest affect welfare record
- **THEN** the panel shows that record with a note that it predates the observer's latest start

### Requirement: The welfare board shows the sleep trigger, the rest and rest requests
The dashboard SHALL follow `sleep.sleep.started`, `sleep.sleep.completed` and `affect.rest_request` through a bridge observer and, when the app starts, SHALL read the newest of them from the last 2000 entries of `sleep.out` and `affect.out`. `GET /diagnostics/sleep.json` SHALL return whether the entity sleeps, the current or last sleep's trigger, start time, duration, developmental rest length and abort flag, and the last rest request's reason, drive, stall length and time. The trigger SHALL be the one the sleep module states (`developmental_rest`, `requested`); otherwise `fatigue` when the completion carries `fatigue_triggered` true, `backstop` when the dashboard saw the sleep's start without a trigger and the completion does not say fatigue, and null when it cannot tell. Labels read from the bus SHALL be kept only when they are lower-case identifiers of at most 40 characters.

#### Scenario: A developmental rest
- **WHEN** `sleep.sleep.started` carries `trigger` "developmental_rest" and the completion carries `rest_seconds` 1260
- **THEN** sleep.json reports the trigger "developmental_rest" and the rest length 1260 s

#### Scenario: An interval sleep
- **WHEN** a sleep starts without a trigger and completes with `fatigue_triggered` false
- **THEN** sleep.json reports the trigger "backstop"

#### Scenario: A spent stimulus
- **WHEN** `affect.rest_request` arrives with reason "stimulus_spent", drive "boredom" and `stall_s` 612
- **THEN** sleep.json reports that request with its time
