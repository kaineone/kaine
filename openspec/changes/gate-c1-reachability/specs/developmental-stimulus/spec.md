## ADDED Requirements

### Requirement: A withdrawal waits for a scorable window
Besides the existing probe bounds, a drive-withdrawal probe SHALL NOT start until `entrainment_window_seconds` has passed since the readout owner started or since the last end of a pause (sleep or freeze). A perturbation probe SHALL keep its existing bounds only.

#### Scenario: An early withdrawal waits
- **WHEN** a withdrawal falls due 84 s after boot with an entrainment window of 300 s
- **THEN** it starts at the first readout step at least 300 s after boot, and its phase-locking value is defined

#### Scenario: A thaw restarts the wait
- **WHEN** a pause ends while a withdrawal is due
- **THEN** the withdrawal waits the entrainment window from the end of the pause

### Requirement: Probe draws and the latest markers persist across restarts
The readout owner SHALL record in `development_progress.json` the withdrawal and perturbation jitter counters, the latest entrain-then-autonomy marker and the latest self-sustain marker (each true, false or null), alongside the existing fields, and SHALL restore them, for the same entity key, before it schedules its first probes.

A file without these fields SHALL load as before, with these values:
- both counters 0;
- the self-sustain marker unknown;
- the entrain-then-autonomy marker true when the restored consecutive-pass count reaches `entrainment_replications`, and unknown otherwise.

A restart SHALL neither reset nor repeat a pass run.

#### Scenario: A restart continues the probe draws
- **WHEN** an owner has drawn jitter for several probes and a new owner starts on the same state for the same entity
- **THEN** the new owner's first draws continue the sequence instead of repeating the first boot's

#### Scenario: A restart keeps a pass run
- **WHEN** two consecutive withdrawals have passed and the owner restarts
- **THEN** the restored count is 2, the readout carries the latest markers before any new withdrawal, and one more passing withdrawal makes the marker true

#### Scenario: An older progress file migrates
- **WHEN** a progress file without the new fields records 3 consecutive passes with 3 replications required
- **THEN** the counters start at 0, the entrainment marker is true and the self-sustain marker is unknown

### Requirement: The period-variability floor lies below fetal values
The maturation gate's period-variability floor `hrv_variability_floor` SHALL default to 0.02, below every fetal five-minute heart-rate coefficient of variation reported by Moraes et al. (2012). This makes it a non-rigidity check, not a maturation target.

#### Scenario: An entrained rhythm passes the floor
- **WHEN** the readout reports a period variability of 0.06 and every other C1 condition holds
- **THEN** C1 passes
