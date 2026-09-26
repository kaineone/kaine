## ADDED Requirements

### Requirement: Measurement probes are gentle and unpredictable to the being
A perturbation probe SHALL raise the maternal drive only to a configured fraction of its bound, strictly above the usual drive and never above the bound (1.5 times the usual drive by default). The time of each probe SHALL vary around its period by a bounded random fraction drawn from a counter-based keyed generator seeded by the run's perception seed, so that the being cannot learn the schedule while a research run with the same seed reproduces it exactly. Jitter SHALL only move due times: every existing bound on probes (durations, frozen state, settling after boot or a thaw, spacing between probes) SHALL continue to apply.

#### Scenario: A perturbation is a bounded rise, not the full bound
- **WHEN** a perturbation probe runs with the default settings
- **THEN** the drive rises to 1.5 times its usual level, stays below its bound, and returns to the usual level when the probe ends

#### Scenario: The schedule cannot be learned
- **WHEN** consecutive probes of one kind are scheduled
- **THEN** their intervals vary within the configured jitter around the period, and a run with the same seed produces the same intervals

#### Scenario: Jitter never relaxes a bound
- **WHEN** a jittered probe falls due while the entity is frozen, settling or near another probe
- **THEN** the probe waits exactly as an unjittered probe would
