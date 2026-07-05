# voice-alignment (delta)

## ADDED Requirements

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
