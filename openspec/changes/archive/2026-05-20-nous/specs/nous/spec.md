## ADDED Requirements

### Requirement: Nous integrates ONA as a long-lived subprocess
Nous SHALL spawn the OpenNARS for Applications `NAR` binary as a child
process on initialize, send Narsese statements via stdin, parse
derivation lines from stdout, and shut the subprocess down cleanly on
module shutdown. The subprocess SHALL be replaceable via a
`NARProcessProtocol` so tests can inject a fake.

#### Scenario: Initialize starts the subprocess
- **WHEN** `Nous.initialize` is awaited with a default `NARProcess`
  pointing at an existing binary
- **THEN** the subprocess is alive and ready to receive Narsese input

#### Scenario: Shutdown terminates the subprocess
- **WHEN** `Nous.shutdown` is awaited
- **THEN** the NAR subprocess exits within 2 seconds and its
  `returncode` is observable

### Requirement: Each workspace broadcast triggers translation and inference
On every `workspace.broadcast` event, Nous SHALL translate each
selected event into a Narsese statement, feed those statements into
the running NAR subprocess, request `inference_steps_per_tick` inference
steps, and publish any new `Derived:`, `Revised:`, or `Answer:` lines
as `nous.belief` events on its `nous.out` stream.

#### Scenario: Selected events become Narsese inputs
- **WHEN** a workspace broadcast contains one selected event with
  `source=soma`, `type=wellness.update`, `salience=0.6`
- **THEN** Nous sends a Narsese statement of the form
  `<soma --> [wellness_update]>. :|: %0.6;0.9%` into the subprocess

#### Scenario: Derivations become nous.belief events
- **WHEN** the NAR subprocess emits a line containing
  `Derived: <X --> Y>. :|: %0.85;0.5%`
- **THEN** Nous publishes a `nous.belief` event whose payload includes
  `statement="<X --> Y>"`, `frequency=0.85`, `confidence=0.5`, and
  `kind="derived"`

### Requirement: Truth-values carry through unchanged
Nous SHALL preserve the `(frequency, confidence)` floats from each
ONA output line exactly in the corresponding published `nous.belief`
event, without clamping, renormalizing, or otherwise transforming
them.

#### Scenario: Exact float preservation
- **WHEN** ONA emits a derivation with `%0.7245;0.5018%`
- **THEN** the published `nous.belief` event has `frequency=0.7245`
  and `confidence=0.5018`

### Requirement: Salience mapping defaults to confidence
By default, the salience of a published `nous.belief` event SHALL
equal the belief's confidence, clamped to `[0.0, 1.0]`. Operators MAY
override the mapping via configuration.

#### Scenario: Default salience equals confidence
- **WHEN** ONA derives `<X --> Y>. :|: %0.8;0.42%`
- **THEN** the published event's salience equals 0.42

### Requirement: NAR restart with exponential backoff
Nous SHALL restart the NAR subprocess on unexpected exit, with an
exponential backoff that starts at 0.5 seconds, doubles on each
consecutive failure, is capped at 30 seconds, and resets after the
subprocess runs stably for at least 5 minutes. Each restart SHALL
publish a `nous.restart` event at the configured alert salience.

#### Scenario: Crash triggers backoff
- **WHEN** the NAR subprocess exits unexpectedly
- **THEN** Nous waits at least 0.5 seconds, publishes a
  `nous.restart` event with alert salience, and starts a new
  subprocess

### Requirement: Setup script produces the binary
The repository SHALL ship `scripts/build-ona.sh` that, on a fresh
clone, clones `https://github.com/opennars/OpenNARS-for-Applications`
into `external/OpenNARS-for-Applications`, runs the upstream
`build.sh`, and confirms the resulting binary launches. The script
SHALL be idempotent — re-running on an existing clone updates and
rebuilds only if upstream source is newer than the binary.

#### Scenario: Fresh clone produces a binary
- **WHEN** an operator on a fresh clone with no existing
  `external/OpenNARS-for-Applications/` runs
  `bash scripts/build-ona.sh`
- **THEN** the script exits 0 and the file
  `external/OpenNARS-for-Applications/NAR` is present and executable

#### Scenario: Re-run on existing binary skips rebuild
- **WHEN** the binary already exists and upstream has no new commits
- **THEN** the script reports that nothing needs rebuilding and exits
  0 without running `./build.sh`

### Requirement: Default Nous config and disabled-by-default
The repository SHALL ship a `[nous]` block in `config/kaine.toml`
with default values for `binary_path`, `inference_steps_per_tick`,
`baseline_salience`, `alert_salience`, and
`restart_backoff_seconds_initial`. The `[modules].nous = false` flag
SHALL keep first boot from auto-registering Nous.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[nous]` section with the documented keys and
  `[modules].nous == false`
