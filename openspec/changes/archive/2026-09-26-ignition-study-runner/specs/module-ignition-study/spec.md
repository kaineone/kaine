## ADDED Requirements

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
