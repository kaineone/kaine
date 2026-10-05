## Why

The operator's goal is the full entity, every module running, by the end of the module-ignition study, and Hypnos voice alignment is part of it. The operator decided (2026-09-30) that the study enables voice alignment only on its final full-entity step, the last accumulate step. Studies must be pre-registered: nothing may change mid-study, so the mechanism must exist in the image before launch.

Voice alignment cannot run where the study runs, inside the `kaine:cuda` container. Verified on main at 459db59:

1. **No trainer in the image.** The image installs `.[test,full,internvideo]`. The `[training]` stack must never enter the runtime venv (`install.py`), and the out-of-process trainer expects a host interpreter (`trainer_python`) that a container cannot run.
2. **The probes are missing from the image,** so boot fails closed. `DEFAULT_ABLITERATION_PROBE_PATH` resolves to `/app/eval_probes/`, which the runtime stage never copies and `.dockerignore` excludes.
3. **No approval variable.** `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` is not passed to the cycle or study containers, although the containerization design lists it.
4. **No base model.** The trainer needs the abliterated organ's HF safetensors. The host has them (`Qwen3.5-4B-abliterated/`), but no container can read them.
5. **An adapter never reaches the organ.** The trainer emits a PEFT adapter. The served organ is a llama.cpp container that loads GGUF LoRAs only at start, cannot see entity state, and can never be restarted from a cycle container (no Docker socket, ever).
6. **Training blocks the cycle.** The subprocess trainer calls `subprocess.run` inside an `async` method, which blocks the cycle's event loop for up to 6 hours.

## What Changes

- **A trainer service.** A `kaine-trainer` compose service (profile `training`) runs an image built from the repository's Dockerfile `trainer` target. It has its own venv with the `[training]` extra and llama.cpp's LoRA→GGUF converter, pinned to the organ's llama.cpp build.
  - **Job loop.** The trainer runs `python -m kaine.modules.hypnos.trainer_service`. It watches a jobs volume shared only with cycle and study containers and runs each ready job through the existing filesystem job contract (`scripts/hypnos_external_train.py`: the capability and abliteration vetoes, then atomic promotion).
  - **GGUF conversion.** It converts a promoted adapter to a GGUF LoRA next to it, and writes `result.json`.
  - **GPU.** It trains on `KAINE_TRAINER_GPU`, by default the organ's GPU, only once the organ reports it is asleep and the free VRAM check passes. Otherwise the job fails loud.
  - **Isolation.** It has no Docker socket, no host ports, and reads models read-only.
- **A job-queue backend.** `trainer_backend = "job_queue"` writes the same job spec into `[hypnos.voice_alignment].trainer_jobs_dir` and awaits `result.json` asynchronously. The timeout is `trainer_timeout_s`, default 6 h. It applies the same fail-loud validation as the subprocess backend. The subprocess backend no longer blocks the event loop; it runs in a worker thread.
- **The organ serves each entity its own adapter, and only to that entity.**
  - **Activation.** The organ container mounts an `organ-adapters` volume read-only. A new hot-swap mode, `organ_adapter`, writes the entity's promoted GGUF adapter into that volume with a manifest naming the adapter's SHA-256, and bumps a generation file.
  - **Loading.** A small launcher that ships with KAINE, the organ container's entrypoint, starts `llama-server` with the active adapter loaded at scale 0 (`--lora-scaled <active>:0 --no-cache-prompt`), and restarts it when the generation changes. `--lora-init-without-apply` is not used: at llama.cpp build b9976 it still applies the adapter to requests that do not ask for it.
  - **Applying.** Lingua sends the per-request `lora` field only when the organ's `GET /lora-adapters` reports this entity's own adapter by path and the manifest's SHA-256 matches. Every other request, including the evaluation A/B baseline, gets the base organ. Hypnos activates the adapter at the end of its sleep window and waits for the organ to answer before the sleep completes.
- **Image and compose.**
  - `eval_probes/` ships in the image.
  - Compose passes `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` (default unset) to the cycle, study and trainer services.
  - A provisioning step copies the abliterated organ's safetensors into the models volume.
- **The study pre-registers the step.** `init` records `voice_alignment_steps` in `study.json`, by default the final accumulate step only, and `build_overlay` enables voice alignment exactly there and disables it explicitly everywhere else.

## Capabilities

### Modified Capabilities
- `voice-alignment-training`: the new `organ_adapter` hot-swap mode.
- `voice-alignment`: the job-queue backend; the subprocess backend never blocks the cycle.
- `module-ignition-study`: pre-registered voice-alignment steps.

## Impact

- **Code:**
  - `kaine/modules/hypnos/` (new `trainer_service.py`, `job_queue_trainer.py`, `organ_adapter.py`; `subprocess_trainer.py`, `hot_swap.py`, `module.py`);
  - `kaine/modules/lingua/client.py`;
  - `kaine/boot.py`;
  - `kaine/research/ignition_study/` (`plan.py`, `overlay.py`, `__main__.py`);
  - `Dockerfile` (`trainer` target, `eval_probes` copy), `.dockerignore`;
  - `docker/organ-launcher.sh`;
  - `compose/kaine.yml` (trainer service, volumes, environment, organ entrypoint);
  - `config/kaine.toml`;
  - a provisioning script.
- **Security:**
  - No container gains the Docker socket or new host ports.
  - The organ reads adapters read-only.
  - The trainer has no internet access (offline Hugging Face) and reads models read-only.
  - An adapter is applied only to its own entity's requests.
- **Unchanged:** the capability and abliteration vetoes, atomic promotion, the two-layer opt-in, the `manual`/`reload_endpoint`/`restart_service` modes, and the in-process and native subprocess paths.
- **Verification:** an end-to-end smoke on this host with no entity. A synthetic preference set on the real 4B base goes through a job, training, the vetoes, promotion, GGUF conversion, activation and an organ reload. A request with the adapter differs from one without, and the A/B baseline is unaffected.
