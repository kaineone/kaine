# voice-alignment Specification

## Purpose
TBD - created by archiving change external-unsloth-trainer. Update Purpose after archive.
## Requirements
### Requirement: Out-of-process voice-alignment trainer
The Hypnos voice-alignment consolidation phase SHALL be able to run its
DPO/QLoRA training in a separate, operator-configured Python environment as an
isolated subprocess, so the entity-runtime interpreter is never coupled to the
trainer's torch/CUDA stack. The trainer interpreter SHALL be configurable
(`[hypnos.voice_alignment].trainer_python`), the training subprocess SHALL
receive the preference pairs, the base-model reference, and the LoRA/DPO
configuration via a filesystem job spec and return a real trained adapter, and
the external training entry point SHALL NOT import the `kaine` package (so the
runtime import boundary is unaffected). The existing capability and abliteration
gates SHALL apply to the returned adapter unchanged.

#### Scenario: External env trains and returns an adapter
- **WHEN** voice-alignment runs with `trainer_backend = "subprocess"` and a valid `trainer_python`
- **THEN** the phase writes the preference pairs + base-model reference + config to a job spec, invokes the configured interpreter as a subprocess, and consumes the adapter it produces — which then passes through the unchanged capability and abliteration gates

#### Scenario: Missing or incompatible trainer env fails loud
- **WHEN** the subprocess backend is selected but the trainer interpreter is unset, missing, exits non-zero, or produces no adapter
- **THEN** the phase raises a clear error (a config error at boot for an unset/invalid interpreter; a training error at run time for a failed subprocess) and NEVER reports a fake or no-op training success

#### Scenario: In-process path retained for compatible hosts
- **WHEN** `trainer_backend = "in_process"` (the shipped default) and the runtime venv has the `[training]` extra
- **THEN** voice-alignment trains in-process exactly as before, unchanged

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

