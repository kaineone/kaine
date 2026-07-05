# oscillatory-binding Specification

## Purpose
TBD - created by archiving change oscillatory-layer. Update Purpose after archive.
## Requirements
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

### Requirement: Disabled coherence layer is bit-for-bit identical across many cycles

The disabled coherence layer SHALL be bit-for-bit identical to the layer absent
across MANY consecutive cycles given the same seed and the same per-cycle events
and phases — not merely for a single tick. On every cycle the selected events,
their order, the salience scores, and the inhibition flag SHALL match the
layer-absent baseline exactly, and the applied coherence multiplier SHALL be a
literal no-op: the disabled path SHALL write no `metadata['coherence']` key and
SHALL leave the salience scores equal to the raw strategy scores (an effective
multiplier of exactly 1.0). The bounded gain map SHALL satisfy
`factor_from_plv(1.0) == coherence_ceiling` and SHALL be monotone non-decreasing
in PLV, so a unit-PLV coalition is mapped to the configured ceiling and never
attenuated.

#### Scenario: Disabled equals absent over many cycles

- **WHEN** a disabled-layer Syneidesis and a layer-absent baseline Syneidesis are
  driven through many consecutive cycles with the same seed and the same per-cycle
  events and phases
- **THEN** on every cycle the selected events, their order, the salience scores,
  and the inhibition flag are identical between the two
- **AND** neither snapshot carries a `metadata['coherence']` key on any cycle

#### Scenario: Disabled multiplier is a literal no-op

- **WHEN** the disabled-layer Syneidesis selects from a set of events
- **THEN** the resulting salience scores equal the raw strategy scores (effective
  multiplier exactly 1.0)
- **AND** no `metadata['coherence']` key is written

#### Scenario: Unit PLV maps to the ceiling

- **WHEN** a `CoherenceScorer` evaluates `factor_from_plv` at PLV 1.0
- **THEN** the returned factor equals `coherence_ceiling`
- **AND** the map is monotone non-decreasing across PLV in `[0, 1]`

### Requirement: Extreme precision gain demonstrably changes selection

An extreme precision gain SHALL demonstrably change selection. With the coherence
layer enabled and the precision gain cranked to an EXTREME ceiling (with a low
floor), Syneidesis selection SHALL FLIP relative to the salience-only baseline: a desynchronized event with higher raw salience
SHALL be overtaken by a phase-locked event with lower raw salience once the
extreme coherence gain is applied. This is a strong proof that the enable toggle
is firmly connected to the selection mechanism, complementing the moderate-gain
control.

#### Scenario: Extreme gain flips the top selection

- **WHEN** the layer is enabled with an extreme `coherence_ceiling` and a low
  `coherence_floor`, a phase-locked source carries a lower raw salience than a
  desynchronized source, and the same inputs are scored with the layer absent
- **THEN** with the layer absent the higher-raw-salience desynchronized event
  ranks first
- **AND** with the extreme-gain layer enabled the phase-locked event overtakes it
  and ranks first, demonstrating the toggle drives selection

### Requirement: Controlled offline oscillatory-ablation runner
The system SHALL provide a controlled, offline oscillatory-ablation runner that
executes the cognitive cycle twice under identical conditions — the same global
seed, the same fixed scripted input, and deterministic mode — differing only in
whether the oscillatory coherence layer is enabled (a real `CoherenceScorer`
with configurable precision gain) or disabled (`coherence=None`, the layer-absent
baseline). The runner SHALL run headless without an entity boot and without
attaching to live modules, the network, or any external service. It SHALL emit a
verdict reporting the measured effect of precision modulation on selection: WIN
when selection is measurably changed by the layer above a configurable floor, and
NULL otherwise, with the effect size carried in the verdict's metrics.

#### Scenario: Enabled-vs-disabled run is reproducible
- **WHEN** the runner is invoked twice with the same seed, stimulus, and gain
- **THEN** the verdict and the reported effect metrics are identical across the two invocations

#### Scenario: Difference is attributable to the layer alone
- **WHEN** the enabled and disabled arms are run
- **THEN** both arms use the same seed, the same scripted input, and deterministic mode
- **AND** the only difference between the arms is the presence of the coherence layer

#### Scenario: A non-trivial stimulus yields a measurable effect
- **WHEN** the runner is given a stimulus in which phase-locked sources and
  desynchronized sources compete and the coherence layer is enabled at a precision
  gain sufficient to re-rank them
- **THEN** the verdict is WIN
- **AND** the reported effect size (selection-divergence fraction) is greater than zero

#### Scenario: The disabled arm matches the layer-absent baseline
- **WHEN** the runner executes the disabled arm
- **THEN** its per-tick trajectory is bit-for-bit identical to a cycle run with no
  coherence layer at all (the layer-absent baseline)

#### Scenario: No measurable difference is reported as null
- **WHEN** the enabled and disabled arms produce identical selection trajectories
- **THEN** the verdict is NULL
- **AND** the reported effect size is zero

#### Scenario: Offline, no entity boot
- **WHEN** the runner is invoked
- **THEN** it drives only the cycle engine and Syneidesis over a scripted in-memory bus
- **AND** it does NOT boot an entity, attach to live modules, or open a network connection

