# hypnos-fatigue-phases Specification

## Purpose
TBD - created by archiving change hypnos-fatigue-phases. Update Purpose after archive.
## Requirements
### Requirement: Fatigue-triggered maintenance with interval safety net
Hypnos SHALL trigger offline maintenance when it observes a `soma.fatigue` event
with `crossed == true`, and SHALL retain `interval_seconds` only as a max-interval
safety net so maintenance still occurs if fatigue never crosses. Non-
interruptibility, deferral, and operator-freeze preemption SHALL be preserved.

#### Scenario: Crossed fatigue triggers maintenance
- **WHEN** Hypnos observes `soma.fatigue` with `crossed == true` and no freeze is
  active
- **THEN** a maintenance cycle begins

#### Scenario: Safety-net interval still fires
- **WHEN** no `soma.fatigue` crossing occurs for the full `interval_seconds`
- **THEN** a maintenance cycle begins anyway

### Requirement: Phase-1 oscillator frequency-reduction hook
Hypnos phase 1 SHALL invoke `ModuleOscillator.set_frequency(scale)` across all
active modules. Before `oscillatory-layer` ships the call SHALL be a no-op;
once `oscillatory-layer` is present modules SHALL slow their LIF oscillators
during the maintenance cycle.

#### Scenario: Hook is a no-op before oscillatory-layer
- **WHEN** `oscillatory-layer` has not shipped and phase 1 runs
- **THEN** no error is raised and module frequencies are unchanged

#### Scenario: Hook reduces frequency when oscillatory-layer is present
- **WHEN** `oscillatory-layer` is present and phase 1 runs
- **THEN** each active module's oscillator frequency is scaled by the configured
  factor

### Requirement: Deep consolidation with global activation downscaling
Hypnos phase 2 SHALL apply global activation downscaling to memory (scaling all
activation weights by `downscale_factor` while preserving relative ordering) and
SHALL open a replay window during which external perception is suspended. The
`mnemos.replay` re-injection SHALL be driven within that window; before
`mnemos-replay` ships this drive is a no-op stub.

#### Scenario: Downscaling preserves ordering
- **WHEN** global activation downscaling is applied
- **THEN** every trace's weight is reduced and the ordering of traces by weight is
  unchanged

#### Scenario: Perception is suspended during replay window
- **WHEN** the phase-2 replay window is open
- **THEN** live external perception capture is suspended for its duration and
  restored afterward

### Requirement: Fatigue reset in phase 4
Hypnos phase 4 SHALL reset Soma's fatigue accumulator to its baseline after
completing the affective-reset step.

#### Scenario: Fatigue resets after maintenance
- **WHEN** a maintenance cycle completes phase 4
- **THEN** Soma's fatigue accumulator is at its baseline

