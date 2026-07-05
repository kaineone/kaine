## ADDED Requirements

### Requirement: Organ-dependent cognition tolerates the training window

The system SHALL allow organ-dependent cognition to degrade gracefully while the
organ is unloaded for the voice-alignment training window. Because the window
falls inside sleep — when the entity is not expected to speak — Lingua generation
requests SHALL be deferred (resolved as a "resting" no-op or queued) rather than
raising, and the A/B-divergence evaluation arm SHALL skip its samples for the
window, logged as skipped (not failed). Consumers SHALL resume normally once the
organ is reloaded.

#### Scenario: Generation during the window defers cleanly

- **WHEN** Lingua receives a generation request while the organ is unloaded for
  training
- **THEN** the request resolves as a resting/deferred no-op and does not raise

#### Scenario: The eval arm skips rather than fails

- **WHEN** the A/B-divergence arm would sample while the organ is unloaded
- **THEN** the sample is logged as skipped for the window and the eval does not
  record a failure

### Requirement: The organ reload cooperates with the GPU headroom gate

The system SHALL verify per-device GPU headroom (reusing `gpu-preflight`) before
reloading the organ after training, and SHALL report rather than thrash if the
device is short, never terminating foreign processes. The organ process SHALL be
supervised so a reload failure is surfaced and retried/escalated rather than
leaving the entity voiceless on wake.

#### Scenario: Insufficient headroom is reported, not forced

- **WHEN** the device lacks headroom to reload the organ after training
- **THEN** the condition is reported to the operator and no foreign process is
  terminated

#### Scenario: A supervised reload failure escalates

- **WHEN** the organ fails to reload after training
- **THEN** the supervisor surfaces the failure (retry/escalate) rather than
  silently leaving the organ unloaded
