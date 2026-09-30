# oscillator-wetware-backend Specification

## Purpose
Oscillatory-binding oscillators whose phase is read from each module's own substrate territory, with the silicon oscillator's semantics.

## Requirements

### Requirement: Module phase can be sourced from the substrate
A `WetwareOscillator` SHALL implement KAINE's `OscillatorProtocol`. Each `step(drive)` SHALL stimulate only the oscillator's own territory and record the firing fraction of the window that answers its own stimulation. Before the substrate follows KAINE's cycle, that window is the one the step runs. Once it follows the cycle, that window is the response to the oscillator's previous step, however many cycle ticks have passed since. Each response SHALL be recorded at most once, and a step before any response exists SHALL record nothing. `phase()` SHALL return the instantaneous phase of the de-meaned firing-fraction history, and SHALL return the neutral phase (0.0) until `plv_window` samples exist or while the series is flat.

#### Scenario: Neutral phase before enough samples
- **WHEN** fewer than `plv_window` samples have been recorded
- **THEN** `phase()` returns 0.0

#### Scenario: Phase is a finite angle
- **WHEN** at least `plv_window` steps with varying drive have been taken
- **THEN** `phase()` returns a finite value in [-pi, pi]

#### Scenario: Shared drive yields coherence
- **WHEN** two oscillators on disjoint territories are stepped with the same slowly varying drive sequence, and two others with drive sequences of clearly different period
- **THEN** the phase-locking value of the first pair over the run is higher than that of the second pair

#### Scenario: A module that publishes rarely records its own response
- **WHEN** the substrate follows the cycle and a module publishes with full drive once every several cycle ticks
- **THEN** each recorded sample is the response to its previous publish, and is far above the background firing of the ticks in between

### Requirement: Hypnos can slow substrate oscillators
`set_frequency(scale)` SHALL set the drive scale (negative values clamp to 0) so that stimulation amplitude is proportional to `drive * scale`, matching the silicon oscillator.

#### Scenario: Deep-sleep slowdown
- **WHEN** `set_frequency(0.5)` is applied and `step(1.0)` is called
- **THEN** the queued stimulation corresponds to half of the full drive

### Requirement: The plugin declares and builds oscillator seams
For each module listed in `[plugins.cl1.oscillators].modules`, the plugin SHALL declare `oscillator.<module>` and SHALL return a `WetwareOscillator` on territory `oscillator.<module>` from `make_oscillator`. The total channels leased across all territories SHALL NOT exceed the usable channels; otherwise `seams` SHALL raise `ValueError`.

#### Scenario: Declared seams
- **WHEN** `oscillators.modules = ["chronos", "soma"]`
- **THEN** `seams` includes `oscillator.chronos` and `oscillator.soma`

#### Scenario: Channel budget exceeded
- **WHEN** the converted-module territories plus `channels_per_module` times the number of oscillated modules exceed 63
- **THEN** `seams` raises `ValueError` naming the budget
