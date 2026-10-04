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

### Requirement: The ignition analysis accounts for time dilation
The ignition analysis SHALL report, for each step, the range of `time_scale` in force and whether it changed, and SHALL report ignitions per tick alongside ignitions per film minute, so that a step run under dilation is not read as a change in the being. The study manifest SHALL record whether automatic dilation was on.

#### Scenario: A dilated step is flagged
- **WHEN** a viewing's ignition records show more than one `time_scale`
- **THEN** that step's report has `time_scale_changed` true, its scale range, and its ignitions per tick

### Requirement: Voice alignment runs only on pre-registered steps
`init` SHALL record `voice_alignment_steps` in the study plan: a list of `{line, k}` steps. It defaults to the final accumulate step only (`{"line": "accumulate", "k": len(order)}`), and the operator can set it explicitly at `init`. The plan SHALL reject unknown lines and out-of-range steps.

`build_overlay` SHALL set `[hypnos.voice_alignment].enabled = true` for exactly those steps and `false` for every other step, overriding any operator setting, so the choice is fixed before launch and recorded in each step's overlay hash. A step with voice alignment enabled SHALL still require the operator approval variable in its environment. Without it, voice alignment stays off by the existing two-layer opt-in, and the step records that.

#### Scenario: Default is the final accumulate step
- **WHEN** a study is initialised with nine modules in `order` and no explicit `voice_alignment_steps`
- **THEN** the plan records `[{"line": "accumulate", "k": 9}]`

#### Scenario: Only the registered step enables voice alignment
- **WHEN** overlays are built for every step of that study
- **THEN** `accumulate` step 9 has `[hypnos.voice_alignment].enabled = true`, and every other step has it `false`, even when the operator configuration enables it

#### Scenario: An invalid registration is refused
- **WHEN** `voice_alignment_steps` names an unknown line or a step outside that line's range
- **THEN** `init` refuses with an error naming the entry

### Requirement: Every study command resolves the study directory the same way
`init`, `run`, `status` and `analyse` SHALL resolve `--study-dir` under the installed data root in the same way, so a study created by `init` is found by the other commands from any working directory.

#### Scenario: A study is found from another directory
- **WHEN** a data root is installed, `init` creates `studies/s1`, and `status --study-dir studies/s1` runs from a different working directory
- **THEN** `status` reads the study `init` created

### Requirement: An unviable gestation ends early, with its data kept and a note written
During a gestation step, until it requests the birth or a disk-low preservation, the study runner SHALL poll the step's `state/lifecycle/gestation_viability.json`, ignoring a file older than the step. On an unviable verdict it SHALL stop the cycle gracefully without requesting a preservation bundle, record the step with outcome `failed:gestation_unviable` and the verdict's evidence, write `ENDED-NOTE.md` into the step directory describing the issue and the evidence, and halt the study for the operator. If stopping the cycle fails, the runner SHALL retry on the next poll; it SHALL NOT send SIGKILL. A verdict SHALL NOT stop or relabel a step whose birth has been requested. It SHALL NOT delete any study data.

#### Scenario: The runner ends an unviable gestation
- **WHEN** the gestation's viability file reports an unviable verdict
- **THEN** the cycle is stopped without a preservation request, the step is recorded as `failed:gestation_unviable`, `ENDED-NOTE.md` exists in the step directory, the study halts, and the step's data remains on disk

#### Scenario: A verdict after birth is ignored
- **WHEN** an unviable verdict file appears after the runner has requested the birth preservation
- **THEN** the cycle is not stopped by the watch and the step is not recorded as `failed:gestation_unviable`

### Requirement: A study records the workspace graph, not every module's output
`build_overlay` SHALL set `[research_event_log.nexus_record].enabled = false`, `[evaluation].workspace_trajectory = false` and `[evaluation].enabled = false` for every study step, overriding any operator setting, and SHALL keep `[ignition_log].enabled = true`. No evaluation observer SHALL run in a study. Run-control and safety records (gestation readouts and viability, preservation and welfare monitors including the gray-zone producer, research events, external utterances, the run manifest) SHALL be unaffected.

#### Scenario: An operator config enables the Nexus record
- **WHEN** the operator config sets `[research_event_log.nexus_record].enabled = true` and `[evaluation].workspace_trajectory = true`
- **THEN** every step's overlay sets both to false and the ignition log stays enabled

#### Scenario: Safety records are kept
- **WHEN** an overlay is built for a gestation step
- **THEN** it still enables the ignition log, the research event log, external utterances and the preservation monitors

#### Scenario: Evaluation observers are off in a study
- **WHEN** the operator config sets `[evaluation].enabled = true`
- **THEN** every step's overlay sets `[evaluation].enabled = false`
