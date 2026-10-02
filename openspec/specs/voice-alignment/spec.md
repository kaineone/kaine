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

### Requirement: A containerized cycle trains through a trainer service
With `trainer_backend = "job_queue"`, the voice-alignment phase SHALL write the existing filesystem job spec (the preference pairs, the base-model reference and the LoRA/DPO configuration) to a new directory under `[hypnos.voice_alignment].trainer_jobs_dir`, mark it ready, and await the trainer service's `result.json` asynchronously. It SHALL wait no longer than `[hypnos.voice_alignment].trainer_timeout_s` (default 21600).

The job's adapter output directory SHALL be inside the job directory, so the trainer service sees only the jobs volume and never the entity's state. The phase SHALL apply the same validation as the subprocess backend: success status, a non-empty adapter directory inside the job directory, and the unchanged capability and abliteration gates. On success, the phase SHALL promote the vetted adapter, together with its GGUF form, into the entity's configured `adapter_output_dir` through the existing atomic promotion. Whatever the outcome, it SHALL delete the job's preference pairs, which are entity language, once the job ends. A timeout, a failed result or a missing adapter SHALL fail loud and SHALL NEVER report a fake or no-op success.

The trainer service (`python -m kaine.modules.hypnos.trainer_service`) SHALL:
- run each ready job with the existing external training entry point;
- convert a promoted adapter to a GGUF LoRA with llama.cpp's converter pinned to the organ's build, and write it beside the adapter;
- write `result.json`;
- start training only after confirming the organ reports that it is asleep and the training device has the configured free VRAM, and otherwise fail the job with the reason;
- never need the Docker socket or host ports.

#### Scenario: A job round-trips through the trainer service
- **WHEN** voice alignment runs with `trainer_backend = "job_queue"` and the trainer service is running
- **THEN** the job spec appears in the jobs directory, the service trains, vetoes or promotes, converts the promoted adapter to GGUF, and writes `result.json`, and the phase consumes it without blocking the cycle

#### Scenario: The trainer never sees entity state
- **WHEN** a job-queue job runs
- **THEN** the job spec names an adapter output directory inside the job directory, the vetted adapter is promoted into the entity's `adapter_output_dir` by the cycle, and the job's `pairs.jsonl` no longer exists after the job ends

#### Scenario: No trainer service fails loud
- **WHEN** no trainer service picks up the job before `trainer_timeout_s`
- **THEN** the phase raises a training error naming the timeout, and no adapter is reported

#### Scenario: A busy organ defers training honestly
- **WHEN** the organ is awake, or the training device lacks the configured free VRAM, when a job is picked up
- **THEN** the service waits a bounded time for the organ to sleep, and otherwise fails the job with the reason, never training on a contended device

### Requirement: The subprocess trainer never blocks the cycle
With `trainer_backend = "subprocess"`, the training subprocess SHALL run without blocking the cycle's event loop. The cycle's other tasks SHALL continue while the trainer runs.

#### Scenario: The cycle keeps ticking during subprocess training
- **WHEN** a subprocess training run takes several seconds
- **THEN** other coroutines on the cycle's event loop keep running during it
