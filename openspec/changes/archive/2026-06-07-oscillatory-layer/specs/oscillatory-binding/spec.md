## ADDED Requirements

### Requirement: Per-module LIF oscillators
Each module SHALL be able to maintain a small snnTorch LIF oscillator population
driven by its own activity and SHALL expose a phase estimate via `phase()`. A
module without an oscillator SHALL report a neutral phase, and the oscillator
SHALL run on CPU.

#### Scenario: Module exposes a phase
- **WHEN** a module with an oscillator has processed several ticks of activity
- **THEN** `phase()` returns a finite phase value

#### Scenario: Absent oscillator is neutral
- **WHEN** a module has no oscillator configured
- **THEN** `phase()` returns the neutral phase and selection is unaffected

### Requirement: Coherence multiplier on coalition salience
Syneidesis SHALL compute the pairwise phase-locking value among the modules
contributing to a candidate coalition over `plv_window` and SHALL multiply the
coalition's aggregate salience by a coherence factor bounded to
`[coherence_floor, coherence_ceiling]`. When `[oscillator].enabled` is false the
factor SHALL be exactly 1.0, leaving selection identical to the pre-change
behavior.

#### Scenario: Disabled layer does not change selection
- **WHEN** `[oscillator].enabled` is false
- **THEN** the coherence factor is exactly 1.0 and the selected coalition matches
  the salience-only baseline

#### Scenario: Phase-locked coalition is favored
- **WHEN** two coalitions have equal aggregate salience but one's source modules
  are phase-locked and the other's are desynchronized, with the layer enabled
- **THEN** the phase-locked coalition receives the higher final score

### Requirement: ModuleOscillator.set_frequency interface
`ModuleOscillator` SHALL expose a `set_frequency(scale)` method that scales the
LIF population's drive frequency by `scale`. This method SHALL be a no-op on
`FakeOscillator` (used in tests). It SHALL be called by `hypnos-fatigue-phases`
phase 1 to slow oscillators during maintenance.

#### Scenario: set_frequency scales drive in live oscillator
- **WHEN** `set_frequency(scale)` is called on a live `ModuleOscillator` with
  scale < 1.0
- **THEN** subsequent drive injections use the scaled frequency

#### Scenario: set_frequency is a no-op on FakeOscillator
- **WHEN** `set_frequency(scale)` is called on a `FakeOscillator`
- **THEN** no error is raised and phase output is unchanged

### Requirement: Spike-to-phase converter with minimum population and window guards
The phase estimator SHALL convert binned spike rates to instantaneous phase using
`scipy.signal.hilbert`. The oscillator population SHALL have at least 16 units and
the PLV window SHALL span at least 10 samples; these SHALL be enforced at
configuration time. The v1 implementation drives oscillators from module
co-activity (publish rate) as a proxy for the paper's content-relatedness; this
approximation SHALL be noted as a limitation in the design document alongside a
v2 sketch (driving LIF from prediction-error magnitude).

#### Scenario: Locked populations yield PLV near 1
- **WHEN** two populations of ≥ 16 units share the same spike train over ≥ 10
  samples
- **THEN** the computed PLV is ≥ 0.95

#### Scenario: Independent populations yield PLV near 0
- **WHEN** two populations of ≥ 16 units spike independently (Poisson, uncorrelated)
  over ≥ 10 samples
- **THEN** the computed PLV is ≤ 0.2

### Requirement: PLV embedded in WorkspaceSnapshot metadata
The oscillatory layer SHALL embed the computed coalition PLV into
`WorkspaceSnapshot.metadata['coherence']` so that it is carried in
`workspace.broadcast` events. The metadata key SHALL be `'coherence'`. When the
layer is disabled, `metadata['coherence']` SHALL be absent or None.

#### Scenario: Coherence key present when layer enabled
- **WHEN** `[oscillator].enabled` is true and a snapshot is broadcast
- **THEN** `snapshot.metadata['coherence']` contains the PLV value for the
  selected coalition's source modules

#### Scenario: Coherence key absent when layer disabled
- **WHEN** `[oscillator].enabled` is false and a snapshot is broadcast
- **THEN** `snapshot.metadata['coherence']` is absent or None
