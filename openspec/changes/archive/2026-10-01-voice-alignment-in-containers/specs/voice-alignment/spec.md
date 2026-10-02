## ADDED Requirements

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
