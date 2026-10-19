# hypnos-fatigue-phases Specification

## Purpose
How fatigue drives the sleep module: maintenance starts when fatigue crosses its threshold or a maximum interval passes, the phases slow the oscillators and downscale activity during deep consolidation, and fatigue resets at the end, without interrupting sleep.

## Requirements

### Requirement: Fatigue-triggered maintenance with interval safety net
The sleep module SHALL trigger offline maintenance when it observes a `interoception.fatigue` event
with `crossed == true`, and SHALL retain `interval_seconds` only as a max-interval
safety net so maintenance still occurs if fatigue never crosses. Non-
interruptibility, deferral, and operator-freeze preemption SHALL be preserved.

#### Scenario: Crossed fatigue triggers maintenance
- **WHEN** the sleep module observes `interoception.fatigue` with `crossed == true` and no freeze is
  active
- **THEN** a maintenance cycle begins

#### Scenario: Safety-net interval still fires
- **WHEN** no `interoception.fatigue` crossing occurs for the full `interval_seconds`
- **THEN** a maintenance cycle begins anyway

### Requirement: Phase-1 oscillator frequency-reduction hook
The sleep module's phase 1 SHALL invoke `ModuleOscillator.set_frequency(scale)` across all
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
The sleep module's phase 2 SHALL first run memory replay and then apply global activation
downscaling to memory (scaling all activation weights by `downscale_factor`
while preserving relative ordering). Replay SHALL run inside a replay window
that the sleep module opens through the episodic memory module immediately before calling `replay_now()` and
closes once replay returns or raises. External perception SHALL be suspended
while the window is open.

#### Scenario: Downscaling preserves ordering
- **WHEN** global activation downscaling is applied
- **THEN** every trace's weight is reduced and the ordering of traces by weight is
  unchanged

#### Scenario: Replay precedes downscaling
- **WHEN** phase 2 runs with the episodic memory module present
- **THEN** `replay_now()` is called before `downscale_activations()`

#### Scenario: Perception is suspended during replay window
- **WHEN** the phase-2 replay window is open
- **THEN** live external perception capture is suspended for its duration and
  restored afterward

### Requirement: Fatigue reset after the affective reset
The sleep module SHALL reset the interoception module's fatigue accumulator to its baseline after the
affective reset that ends the sleep, through the `sleep.sleep.completed`
event that follows it.

#### Scenario: Fatigue resets after maintenance
- **WHEN** a maintenance cycle completes its affective reset
- **THEN** the interoception module's fatigue accumulator is at its baseline
