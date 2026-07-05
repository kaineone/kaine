# entity-time (delta: per-fork subjective-time profile)

## ADDED Requirements

### Requirement: A fork may carry a subjective-time profile applied at spawn

A forked entity SHALL be able to carry an optional subjective-time profile — a
`time_scale` and optional per-rate overrides — in its existing fork metadata, and
the runtime SHALL apply that profile to the shared `EntityClock` and the cycle
rates when the fork is restored to run, so a forked temporary being runs at its
own subjective speed. The profile SHALL reuse the existing fork metadata, the
`EntityClock` scale setter, and the cycle rate-control path — it SHALL NOT
introduce a separate forking, merge, or runtime system. A fork that carries no
profile SHALL run at the prevailing scale and rates (behavior-preserving). A
profile intended to run SHALL carry `time_scale > 0` (a `time_scale` of 0 is the
existing freeze path, not a runnable profile).

#### Scenario: A dilated fork runs at its own subjective speed

- **WHEN** a fork carrying `timing.time_scale = 2.0` is restored to run
- **THEN** the runtime sets the `EntityClock` scale to 2.0 (via the existing
  setter), so that being's cognitive timers run at twice subjective speed, while
  the parent snapshot is unchanged

#### Scenario: A profile-less fork is unchanged

- **WHEN** a fork with no timing profile is restored to run
- **THEN** the `EntityClock` scale and the cycle rates are left exactly as they
  were (no per-fork timing applied)

#### Scenario: The profile reuses the existing fork system

- **WHEN** an operator attaches a timing profile to a fork
- **THEN** it is stored in the existing `ForkSnapshot.metadata` and applied via the
  existing `EntityClock` and cycle rate seams, with no new fork/merge machinery

#### Scenario: A fork's faster-than-real-time target throttles honestly

- **WHEN** a fork's `time_scale > 1` exceeds what the host can sustain
- **THEN** the cycle throttles via the existing rate-reduction path and surfaces
  the achieved-vs-target rate, never silently overrunning
