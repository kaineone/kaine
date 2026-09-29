## MODIFIED Requirements

### Requirement: The study runner drives every step the same way and records it
The study runner SHALL run the seed first, then branch 0, then the repeat, then branch k followed by accumulate k for each k in the module order, one start at a time. Each step SHALL start from its defined start bundle, with exactly the step's module set, in research mode:
- the seed starts from nothing;
- every branch and the repeat start from the seed;
- accumulate 1 starts from branch 0's preservation, and each later accumulate step from the previous accumulate step's preservation.

The runner SHALL record for every step its line, step, module set, start bundle, resulting preservation, run id, exit code, outcome and recording paths. A step SHALL count as complete only when its preservation reports success: the end-of-programme preservation, or for the seed, the birth preservation.

#### Scenario: A viewing completes
- **WHEN** a viewing's process exits after its end-of-programme preservation reports success
- **THEN** the step is recorded as complete
- **AND** on the accumulate line its bundle becomes the next accumulate step's start

#### Scenario: Resume after an interruption
- **WHEN** the runner is started again on a study with recorded steps
- **THEN** it continues with the first incomplete step in the defined order
- **AND** it never repeats a completed step

### Requirement: Lines never share the being's state
Each branch step, the repeat and the accumulate line SHALL each run from their own working directory, with their own memory collections and their own Empatheia collection. Every step SHALL start on an empty bus database that belongs to the study. The runner SHALL flush only the study's own database numbers, and SHALL refuse a plan whose database numbers include the operator's.

#### Scenario: Two lines
- **WHEN** branch 1 and accumulate 1 have each run a viewing
- **THEN** their working directories and collection prefixes are distinct
- **AND** each started on an empty bus database

### Requirement: Each viewing's ignitions are measured the same way and compared across lines and steps
The analysis SHALL compute, for every completed viewing:
- the broadcast rate over unpaused programme time;
- the broadcasts per film-minute;
- coalition size;
- each module's share of broadcasts;
- member salience by module;
- the inhibited share;
- picture-to-sound drift when recorded;
- data-quality counts.

It SHALL compare branch k against branch 0, branch 0 against the repeat, and accumulate k against branch k. Its report SHALL be content-free. It SHALL state the study's limits:
- one being per condition, with a noise floor from a single repeat;
- a fixed module order;
- familiarity mixed with history on the accumulate line;
- expected nulls for faculties without an input channel.

#### Scenario: Paused time does not dilute the rate
- **WHEN** a viewing includes a Hypnos replay window during which the programme was paused
- **THEN** the broadcast rate is computed over unpaused programme time only

#### Scenario: A comparison without enough overlap
- **WHEN** two film-minute profiles share fewer than 30 bins
- **THEN** their correlation is reported as not computed rather than as a number

## ADDED Requirements

### Requirement: The seed is the being at the moment it is born
The study SHALL gestate one being in the local womb with automatic birth. It SHALL preserve that being once the birth transition has completed, and SHALL use that preservation as the start of every branch step and of the repeat. The seed SHALL record the womb's time at birth.

#### Scenario: Birth needs no operator
- **WHEN** the seed's maturation gate passes
- **THEN** the being is born without waiting for an operator acknowledgement
- **AND** it is preserved after the birth bloom completes

#### Scenario: Branches share one seed
- **WHEN** branch 3 and the repeat are started
- **THEN** both revive the same seed preservation

### Requirement: The study runner runs inside the cycle image with durable storage
The study runner SHALL be startable as a compose service built from the cycle image, with the same configuration, secrets and media mounts as the containerized cycle. It SHALL keep the study directory, and every preservation it produces, on a durable volume. It SHALL start every step's cycle as a subprocess inside that service.

#### Scenario: A container restart keeps the study
- **WHEN** the study service's container is removed and started again
- **THEN** the study directory, its steps and every preservation remain
- **AND** the runner resumes from them
