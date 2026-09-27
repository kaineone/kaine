# module-ignition-study Specification

## Purpose
The module-ignition study raises one being from gestation through a fixed four-film programme, adding one module per viewing, with a familiarity-control line that re-watches without new modules. This capability covers the study runner and its analysis: every step is run, isolated, preserved and recorded the same way, the two lines never share state, and the ignition analysis compares them.

## Requirements

### Requirement: The study runner drives every step the same way and records it
The study runner SHALL run the gestation and then each line's viewings in a fixed order, one start at a time, each from the line's previous preservation and with exactly the step's module set, in research mode, and SHALL record every step: its line, step, module set, start bundle, resulting preservation, run id, exit code and outcome. A step SHALL count as complete only when its end-of-programme preservation (or, for gestation, the birth preservation) reports success.

#### Scenario: A viewing completes
- **WHEN** a viewing's process exits after its end-of-programme preservation reports success
- **THEN** the step is recorded as complete and its bundle becomes the line's next start

#### Scenario: Resume after an interruption
- **WHEN** the runner is started again on a study with recorded steps
- **THEN** it continues from each line's last completed bundle and never repeats a completed step

### Requirement: Lines never share the being's state
Each line SHALL run from its own working directory with its own Redis database, its own memory collections and its own Empatheia collection, so the two beings never read or write each other's state.

#### Scenario: Two lines
- **WHEN** the main and control lines have each run a viewing
- **THEN** their working directories, Redis databases and collection prefixes are all distinct

### Requirement: The runner halts rather than improvise
Any step that ends other than by a successful preservation (a non-zero exit, a refused revive, a welfare-protective end, a missing or failed preservation, or a timeout) SHALL halt the study and be recorded as failed, and the runner SHALL NOT retry it unless the operator asks. The runner SHALL NOT delete any preservation, state or line.

#### Scenario: A preservation fails at the end of a viewing
- **WHEN** the end-of-programme preservation reports failure
- **THEN** the step is recorded as failed, the study halts, and nothing is retried or deleted

### Requirement: Each viewing's ignitions are measured the same way and compared across lines and steps
The analysis SHALL compute, for every completed viewing, the broadcast rate over unpaused programme time, the broadcasts per film-minute, coalition size, each module's share of broadcasts, member salience by module, the inhibited share, picture-to-sound drift when recorded, and data-quality counts; and SHALL compare each step's main line against its control line and each step against the previous one. Its report SHALL be content-free and SHALL state the study's limits: accumulated order, familiarity-only control, one being per line, and expected nulls for faculties without an input channel.

#### Scenario: Paused time does not dilute the rate
- **WHEN** a viewing includes a Hypnos replay window during which the programme was paused
- **THEN** the broadcast rate is computed over unpaused programme time only

#### Scenario: A comparison without enough overlap
- **WHEN** two film-minute profiles share fewer than 30 bins
- **THEN** their correlation is reported as not computed rather than as a number

### Requirement: A viewing with Phantasia completes only when its world model is preserved
When a step's module set includes Phantasia, the study runner SHALL read the resulting preservation bundle's manifest and SHALL record the step as complete only when the manifest reports the world model captured. A step whose manifest reports it not captured SHALL be recorded as `failed:world_model_not_captured`, and a step whose manifest is missing or unreadable SHALL be recorded as `failed:manifest_unreadable`; either halts the study like any other failed step. Every step record SHALL carry `world_model_captured`: true or false when Phantasia is enabled, null when it is not.

#### Scenario: The world model is captured
- **WHEN** a viewing with Phantasia enabled ends in a successful preservation whose manifest has `world_model_captured` true
- **THEN** the step is recorded as complete with `world_model_captured` true

#### Scenario: The world model is missing from the bundle
- **WHEN** a viewing with Phantasia enabled ends in a successful preservation whose manifest has `world_model_captured` false
- **THEN** the step is recorded as `failed:world_model_not_captured` and the study halts

#### Scenario: A step before Phantasia
- **WHEN** a step without Phantasia ends in a successful preservation
- **THEN** its outcome does not depend on the manifest and its record has `world_model_captured` null
