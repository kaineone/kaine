## ADDED Requirements

### Requirement: Module phase can be sourced from the substrate

A `WetwareOscillator` SHALL implement KAINE's `OscillatorProtocol` (`phase()`,
`step()`, `set_frequency()`), driving and reading a substrate channel territory,
so a module's binding phase derives from biological bursting instead of a silicon
LIF. Modules without a substrate oscillator SHALL report the neutral phase,
preserving upstream behaviour.

#### Scenario: Phase drives coherence

- **WHEN** two modules are driven from substrate territories at the same frequency
- **THEN** their phase-locking value (PLV) coherence is high
- **AND** at detuned frequencies their coherence is low

#### Scenario: Neutral phase without an oscillator

- **WHEN** a module has no substrate oscillator attached
- **THEN** it reports the neutral phase and does not perturb workspace selection

### Requirement: Hypnos can slow substrate oscillators

`set_frequency(scale)` SHALL scale the entrainment frequency so Hypnos deep-sleep
maintenance can slow module oscillators as it does for the silicon oscillator.

#### Scenario: Deep-sleep slowdown

- **WHEN** `set_frequency(0.5)` is applied during a maintenance phase
- **THEN** the effective phase-advance rate is measurably halved
