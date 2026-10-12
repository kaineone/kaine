## RENAMED Requirements

- FROM: `### Requirement: Fatigue reset in phase 4`
- TO: `### Requirement: Fatigue reset after the affective reset`

## MODIFIED Requirements

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
affective reset that ends the sleep, through the `hypnos.sleep.completed`
event that follows it.

#### Scenario: Fatigue resets after maintenance
- **WHEN** a maintenance cycle completes its affective reset
- **THEN** the interoception module's fatigue accumulator is at its baseline
