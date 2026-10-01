## 1. Cycle side
- [ ] 1.1 `kaine/modules/hypnos/job_queue_trainer.py`: `JobQueueTrainer`. It writes the job spec (reuse `SubprocessTrainer`'s job writer) to `<trainer_jobs_dir>/<job id>/`, touches `READY` last, awaits `result.json` with `asyncio.sleep` polling up to `trainer_timeout_s`, validates as `SubprocessTrainer` does, and returns the same `TrainingResult`. The job spec's adapter output directory is `<job>/out`, so the trainer never sees entity state. On success the vetted adapter, with `adapter.gguf`, is copied into the entity's `adapter_output_dir` through `adapter_store.tmp_dir_for`/`final_dir_for`/`promote`. `pairs.jsonl` is deleted when the job ends, whatever the outcome.
- [ ] 1.2 `kaine/modules/hypnos/subprocess_trainer.py`: run the subprocess in `asyncio.to_thread`.
- [ ] 1.3 `kaine/boot.py` and `config/kaine.toml`:
  - `trainer_backend = "job_queue"`, `trainer_jobs_dir` (default `state/hypnos/voice_align_jobs`) and `trainer_timeout_s` (default 21600), validated;
  - `hot_swap_mode = "organ_adapter"`, with `organ_adapters_dir` (default `/organ-adapters`) and `organ_url` taken from `[lingua].chat_url`.
- [ ] 1.4 `kaine/modules/hypnos/organ_adapter.py`: `activate(adapter_dir, adapters_volume, entity_adapter_sha256)` writes `active.gguf` (atomic copy of the adapter's `adapter.gguf`) and `active.json` (`{"sha256", "adapter_id", "activated_at"}`), then bumps `generation`. `wait_ready(organ_url, timeout)` polls `/health`. Hot-swap `dispatch` gains the `organ_adapter` mode, and Hypnos awaits `wait_ready` before completing the sleep.
- [ ] 1.5 `kaine/modules/lingua/client.py`: an optional `lora_resolver` supplies the per-request `lora` field. The resolver reads the organ's `GET /lora-adapters` and `active.json`, and returns the id only when the path and the SHA-256 match this entity's promoted adapter. It caches per generation and logs once per change. The evaluation A/B client never uses a resolver.

## 2. Trainer service and image
- [ ] 2.1 `kaine/modules/hypnos/trainer_service.py`: a polling job loop.
  - **Job handling.** It claims a job atomically (renames `READY` to `CLAIMED`), runs `scripts/hypnos_external_train.py` with `KAINE_TRAINER_PYTHON`, and on promotion runs the GGUF converter (`KAINE_LORA_CONVERTER`) to `adapter.gguf`. It writes `result.json` atomically.
  - **Before training.** It checks the organ is asleep (`/props` `is_sleeping`) and that the device has at least `--min-free-mib` free (`nvidia-smi` or pynvml), waiting up to `--organ-wait-s`.
  - **Refusals.** It never trains on a contended device, never follows symlinks out of the jobs directory, and caps concurrent jobs at one.
- [ ] 2.2 `Dockerfile`: a `trainer` target. It is based on the runtime image with a separate venv at `/opt/trainer` that has the `[training]` extra (with torch constrained the same way) and the `gguf` package. It also contains llama.cpp's `convert_lora_to_gguf.py` at the organ's pinned build, fetched at build time and verified by SHA-256.
- [ ] 2.3 `Dockerfile` runtime: `COPY eval_probes /app/eval_probes`. In `.dockerignore`, allow `eval_probes/`.
- [ ] 2.4 `compose/kaine.yml`:
  - a `kaine-trainer` service (profile `training`, the organ's GPU through `KAINE_TRAINER_GPU`, the `kaine-models:ro` and `kaine-trainer-jobs` volumes, the compose network, no ports, `HF_HUB_OFFLINE=1`);
  - `kaine-trainer-jobs` mounted into the cycle and study at the jobs directory;
  - `organ-adapters` mounted read-write into the cycle and study, and read-only into the organ;
  - the organ's entrypoint is the launcher;
  - `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` is passed to the cycle, study and trainer.
- [ ] 2.5 `docker/organ-launcher.sh`: POSIX sh. It validates the SHA-256 of `active.gguf` against `active.json`, starts `llama-server "$@"` plus `--lora … --lora-init-without-apply` when valid, polls `generation`, restarts on change, and forwards signals.
- [ ] 2.6 `scripts/provision_organ_base.sh`, or a `kaine.setup` step: copy the abliterated organ's HF safetensors into the models volume (`/models/Qwen3.5-4B-abliterated`), owned by the container user, and verify the file hashes.

## 3. Study
- [ ] 3.1 `kaine/research/ignition_study/plan.py` and `__main__.py`: a `voice_alignment_steps` plan field with default and validation, and `init --voice-alignment-step LINE:K` (repeatable).
- [ ] 3.2 `kaine/research/ignition_study/overlay.py`: enable voice alignment on the registered steps and disable it explicitly elsewhere, with the job-queue backend and the `organ_adapter` mode on the enabled steps.

## 4. Tests
- [ ] 4.1 `JobQueueTrainer`: round trip with a fake service; timeout; a failed result; a missing adapter; it does not block the event loop.
- [ ] 4.2 The subprocess trainer does not block the loop.
- [ ] 4.3 `trainer_service`, with a fake train script and a fake converter:
  - the claim is atomic;
  - the organ-awake wait and refusal;
  - the VRAM refusal;
  - `result.json` contents;
  - symlink refusal;
  - one job at a time.
- [ ] 4.4 `organ_adapter`: activation files are atomic, and the generation is bumped. The Lingua resolver sends the field only when the path and SHA-256 match, sends none otherwise, and the A/B client never sends it.
- [ ] 4.5 The launcher, run as a real script with a fake `llama-server` that records its argv: the flags are added only when the SHA-256 is valid, and it restarts on a new generation.
- [ ] 4.6 Study: the default registration, validation, and the overlays of every step.
- [ ] 4.7 Image smoke in CI: `eval_probes` is present, and `import kaine.modules.hypnos.trainer_service` works.

## 5. End-to-end smoke (on this host, no entity)
- [ ] 5.1 Provision the base model, build the trainer image, and start the trainer.
- [ ] 5.2 Submit a synthetic preference job through `JobQueueTrainer` against the real 4B base. It is trained, vetted, promoted and converted.
- [ ] 5.3 Activate it. The organ reloads with the adapter unapplied. A request with the `lora` field differs measurably from one without (the logprobs of a fixed prompt), and a request without it matches the base.
- [ ] 5.4 Record the results in the PR.

## 6. Docs
- [x] 6.1 `docs/hypnos.md` or VOICE_ALIGNMENT.md, `docs/configuration.md`, the deployment docs, and the study docs.
