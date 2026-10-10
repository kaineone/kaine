# Containers

KAINE's container deployment runs the supporting services, the dashboard, the cognitive cycle, the study runner and the voice-alignment trainer as one Compose project (`compose/kaine.yml`). This page is for operators who build, provision and run KAINE with Docker or Podman. It covers the container topology, how to start services without booting an entity by accident, and how state, secrets and boot gates are handled.

With no profile selected, the configuration loader applies the base-thesis `thesis_test` profile. It turns on `soma`, `chronos`, `topos`, `audition`, `lingua`, `thymos` and `hypnos` and turns every other module off. It also sets `[perception_feed].mode = "seeded"` with `seed = 0`, `[topos].foveation = true`, `[audition].transcription_enabled = false` with `general_audition = true`, `[lingua].temperature = 0.0`, `[chronos].forward_prediction = true`, and `[volition]` with `policy = "self_initiated_report"`, `drive_initiative = false` and `sig_expiry_s = 300.0`. Every other value, from the organ model to the rates, comes from the shipped `config/kaine.toml`, which sets `[perception_feed].mode = "off"`, `[hypnos.voice_alignment].hot_swap_mode = "manual"` and `trainer_backend = "in_process"`, and `[security.state_encryption].enabled = true`.

`config/kaine.operator.toml` merges last and wins. The first-run wizard (`python -m kaine.setup`) writes a full `[modules]` table there, so after the wizard runs, its module choice replaces the profile's. The wizard offers two presets: the base-thesis set (the `thesis_test` modules) and a full set with every cognitive module except Perception and Mundus. It recommends the full set on a Tier 2 or Tier 3 host that needs no module residency and the base-thesis set otherwise.

## Topology

| Service | Role | Host endpoint | GPU |
|---|---|---|---|
| `kaine-redis` | event bus (Redis Streams) | `127.0.0.1:6479` (`KAINE_REDIS_HOST_PORT`) | none |
| `kaine-qdrant` | vector store | `127.0.0.1:6533` (`KAINE_QDRANT_HOST_PORT`) | none |
| `kaine-model-server` | OpenAI-compatible language organ (llama.cpp `llama-server`) | `127.0.0.1:11434` (`KAINE_MODEL_SERVER_HOST_PORT`) | card 0 (`KAINE_ORGAN_GPU`) |
| `kaine-speaches` | speech-to-text (faster-distil-Whisper) | `127.0.0.1:8000` (`KAINE_SPEACHES_HOST_PORT`) | none, CPU only |
| `kaine-chatterbox` | text-to-speech | `127.0.0.1:8883` (`KAINE_CHATTERBOX_HOST_PORT`) | card 1 (`KAINE_VISION_GPU`) |
| `kaine-nexus` | dashboard (`python -m kaine.nexus`, served by uvicorn) | `127.0.0.1:8088` (`KAINE_NEXUS_HOST_PORT`) | none |
| `kaine-cycle` | the cognitive cycle, which is the entity (`--profile cycle`) | none | card 1 |
| `kaine-study` | runner of the module-addition study, called the ignition study in code (`--profile study`) | none | card 1 |
| `kaine-trainer` | voice-alignment trainer service (`--profile training`) | none | `KAINE_TRAINER_GPU`, defaulting to the organ's card |
| `kaine-provision` | one-shot model download (`--profile setup`) | none | none |

Every published port is bound to `127.0.0.1`. Inside the Compose network, services reach the organ at `http://kaine-model-server:8080/v1` and the bus at `kaine-redis:6379`. Set `KAINE_MODEL_SERVER_HOST_PORT` in `compose/.env` when another program on the host, such as a system Ollama, already holds port 11434.

`kaine-chatterbox` defaults to the image `kaine-chatterbox:local`, which has no upstream source. A plain `docker compose -f compose/kaine.yml up` fails until you build that image or set `KAINE_CHATTERBOX_IMAGE` to one that exists.

`kaine-nexus`, `kaine-cycle`, `kaine-study` and `kaine-provision` use the same runtime image with different commands. `kaine-trainer` uses the separate `kaine:trainer-<flavor>` image.

## Opening Nexus

Open `http://127.0.0.1:8088/diagnostics/` on the host. The shipped `[nexus].access` is `"open"`, so no token or sign-in is needed. Compose passes these Nexus variables from `compose/.env`: `KAINE_NEXUS_ACCESS` (`open` or `token`), `KAINE_NEXUS_TOKEN`, `KAINE_NEXUS_EXTRA_HOSTS` (tailnet names to add to the allowed hosts and origins) and `KAINE_NEXUS_HOST_PORT`, which also sets `KAINE_NEXUS_PUBLISHED_PORT` and the allowed origins. `compose/.env.example` lists only `KAINE_NEXUS_HOST_PORT`.

The service sets `KAINE_NEXUS_HOST=0.0.0.0` (the bind inside the container, so the published loopback port can reach it), `KAINE_NEXUS_NON_LOOPBACK_ALLOWED=1` and `KAINE_NEXUS_ALLOWED_ORIGINS` to the loopback origins. Nexus also reads `KAINE_NEXUS_PORT`, `KAINE_NEXUS_CONVERSATION_ENABLED` and `KAINE_NEXUS_READ_ONLY`, but Compose does not pass them, so setting them in `.env` has no effect. To make the dashboard read-only, set `[nexus].read_only = true` in `config/kaine.operator.toml`, which is mounted into the container, or pass the variable through a local overlay (`compose/*.local.yml` files are ignored by git). Host and Origin checks always apply, and `/` redirects to `/diagnostics/` when conversation is off. See [Nexus, the dashboard](../05-nexus.md).

## The images

The [Dockerfile](../../Dockerfile) builds two targets:

- `runtime`, the default image, tagged `kaine:<flavor>`;
- `trainer`, tagged `kaine:trainer-<flavor>`, used by the voice-alignment service.

The `FLAVOR` build argument selects the matching PyTorch build. Before the package is installed, `kaine/wheel_index.py` runs on its own to print the wheel index (`--image-index <flavor>`) and the torch requirement from `pyproject.toml` (`--torch-spec`). The installed `torch`, `torchvision` and `torchaudio` versions are then pinned as constraints for the package install. The default extras are `.[test,full]` in the Dockerfile; Compose builds with `KAINE_EXTRAS=.[test,full,internvideo]`.

```bash
# CUDA runtime (default)
docker build -t kaine:cuda .

# CPU runtime
docker build -t kaine:cpu \
  --build-arg FLAVOR=cpu \
  --build-arg BUILD_BASE=python:3.12-slim \
  --build-arg RUNTIME_BASE=python:3.12-slim .

# Trainer image
docker build --target trainer -t kaine:trainer-cuda .
```

`KAINE_FLAVOR` accepts `cuda`, `cpu`, `rocm` and `xpu`. ROCm and XPU are experimental until validated on real hardware, and CPU is the fallback that always works.

The runtime image runs as the non-root user `kaine` (uid 10001) under `tini`, sets `HF_HOME=/models/hf`, `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, and runs `python -m kaine.cycle` by default.

## Provision models once

Weights are provisioned into the shared `kaine-models` volume before first boot and never live in an image layer:

```bash
cp compose/.env.example compose/.env      # then fill in the secrets
docker compose -f compose/kaine.yml --profile setup run --rm kaine-provision
```

The service runs `python -m kaine.setup.provision`. It downloads the abliterated organ, the InternVideo-Next weights (the default vision encoder; DINOv2-small instead when `[topos].encoder_backend = "dinov2"`), the all-MiniLM-L6-v2 embedder and emotion2vec+. It downloads faster-distil-Whisper when Audition uses the Speaches backend and Chatterbox when Vox uses the Chatterbox backend, which are the shipped backends. The sherpa-onnx speech archives (Kokoro, which bundles the espeak-ng data, Moonshine and any other speech model Audition or Vox selects) are fetched only when a module selects `"sherpa_onnx"` and the operator passes `--speech-models` or sets `KAINE_PROVISION_SPEECH_MODELS=1` after the plan has shown each archive's name, size and licence.

Provisioning is the only phase that fetches models. At runtime the containers set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

## Bring up the supporting services

```bash
docker compose -f compose/kaine.yml up -d
```

This starts the bus, the vector store, the model server, the speech services and Nexus. It does not start the entity: `kaine-cycle` has `profiles: [cycle]`, so a plain `up` never runs it. A bare `docker run kaine:<flavor>` does not start an entity either, because the cycle refuses to boot without the operator gate.

CPU-only and single-GPU hosts add an overlay:

```bash
# CPU-only
KAINE_FLAVOR=cpu docker compose -f compose/kaine.yml -f compose/kaine.cpu.yml up -d

# Single GPU
docker compose -f compose/kaine.yml -f compose/kaine.single-gpu.yml up -d
```

`compose/kaine.cpu.yml` switches `kaine-nexus`, `kaine-cycle` and `kaine-study` to the `kaine:cpu` image, uses the CPU build of the model server, and drops the GPU reservations from `kaine-model-server`, `kaine-chatterbox`, `kaine-cycle`, `kaine-study` and `kaine-trainer`. The trainer's own device check refuses to train on a CPU host; its reservation is dropped only so the stack renders. `compose/kaine.single-gpu.yml` moves `kaine-chatterbox`, `kaine-cycle` and `kaine-study` to card 0, where the organ already runs.

The card numbers come from `KAINE_ORGAN_GPU` and `KAINE_VISION_GPU`. The first-run wizard writes them to `compose/.env` from the `[hardware.devices]` map it records. `KAINE_TRAINER_GPU` is not part of that map; when it is unset, the trainer uses the organ's card.

## Start the cognitive cycle

Booting the cycle is a deliberate, supervised step:

```bash
KAINE_CYCLE_OPERATOR_PRESENT=1 \
  docker compose -f compose/kaine.yml --profile cycle run --rm kaine-cycle
```

See [First boot](../04-getting-started/first-boot.md) for the supervised boot. `KAINE_RESEARCH_MODE=1` replaces the operator-present gate with the research gate, which refuses to boot unless preservation, the welfare response, logging, the dry preserve-and-revive self-check and the individuation producer are all active, and encryption too when it is required. Compose does not pass `KAINE_CYCLE_UNATTENDED` to `kaine-cycle`; select unattended mode with `[cycle].supervision_mode` in the mounted operator config.

## GPU passthrough

With Docker and the NVIDIA Container Toolkit, `compose/kaine.yml` reserves devices through `deploy.resources.reservations.devices`: the organ on card 0, and Chatterbox, the cycle and the study runner on card 1. Install the toolkit on the host first.

With rootless Podman, generate the CDI specification once so that the quadlet `AddDevice=nvidia.com/gpu=N` lines take effect:

```bash
nvidia-ctk cdi generate --output=$HOME/.config/cdi/nvidia.yaml
```

For AMD GPUs (experimental), add `compose/kaine.rocm.yml`. It passes `/dev/kfd` and `/dev/dri` to the model server, Chatterbox and the cycle, adds the `video` and `render` groups, and switches the model server to its ROCm build.

## Where the organ runs

By default the organ runs inside `kaine-model-server`, with `docker/organ-launcher.sh` as its entrypoint. The Compose service and the quadlet unit both check health by requesting `http://127.0.0.1:8080/health` without an API key. The organ unloads after `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` idle seconds (default 600; `-1` keeps it loaded) and reloads on the next request. If you override `KAINE_MODEL_SERVER_CMD`, pass `--fit off`, `-c`, `-np` and `--sleep-idle-seconds` yourself; without `-c`, loading allocates the model's full training context and runs out of GPU memory.

The organ image comes from `KAINE_MODEL_SERVER_IMAGE`. Its default is llama.cpp build b11382 pinned by digest (`ghcr.io/ggml-org/llama.cpp@sha256:ef08b5a98b1170f2b62177be0a4027c88a84043c55afbf190dd18b9e7cdcfebf`) for CUDA; `compose/kaine.rocm.yml` and `compose/kaine.cpu.yml` pin their own digests of the same build.

The launch flags are explicit:

- every model layer goes on the GPU, with automatic fitting off and `-ngl` set by `KAINE_MODEL_SERVER_NGL` (default 999), so a GPU that is too small fails loudly;
- the prompt cache in RAM is capped by `KAINE_MODEL_SERVER_CACHE_RAM_MIB` (default 1024 MiB);
- the context is 32768 tokens (`KAINE_MODEL_SERVER_CTX`) shared by 4 slots (`KAINE_MODEL_SERVER_PARALLEL`);
- the KV cache is f16 (`-ctk f16 -ctv f16`);
- slot saving is never enabled, because it would write KV cache derived from sense data to disk.

Because fitting is off, the organ's reload after idle sleep fails if another process holds the VRAM it needs. Keep the GPU free of other models while an entity runs.

A run whose system changes in the middle of a study is not admissible. After changing the image, check that the flags KAINE passes still exist in the new build's `--help` (`--sleep-idle-seconds`, `--lora-scaled`, `--no-cache-prompt`, `--alias`, `--fit off`, `-ngl`, `--cache-ram`, `-c`, `-np`, `-ctk` and `-ctv`), then run `python -m kaine.preboot` again.

The `kaine-trainer` service can run voice alignment next to the organ in its container, so no organ server on the host is needed. For `hot_swap_mode = "organ_adapter"`, mount `kaine-organ-adapters` at `organ_adapters_dir` (default `/organ-adapters`). When an activation raises the adapter generation, the launcher restarts `llama-server` in the same container with the adapter loaded at scale 0 (`--lora-scaled <path>:0 --no-cache-prompt`): requests without a `lora` field get the base organ, requests with one apply the adapter, and prompt caching is off while an adapter is loaded. This mode works only in Compose, because the quadlet model-server unit does not use the launcher or the adapter volume.

To use an organ server on the host instead, such as an Unsloth server that shares one process for inference and training, add `compose/kaine.organ-host.yml`, which disables `kaine-model-server` and maps `host.docker.internal` to the host gateway for Nexus and the cycle. Point `[lingua].chat_url` at `http://host.docker.internal:11434/v1` (`host.containers.internal` on Podman). When `model_server` is declared a shared service (`[services.model_server].shared = true`), KAINE forces `[hypnos.voice_alignment].hot_swap_mode` to `"manual"`, because the cycle cannot manage the adapters of a server it does not own. A host server that is not declared shared does not trigger that override.

## Voice alignment

The `kaine-trainer` service runs only under the `training` profile. It sees the shared job volume and the model weights read-only, with no entity state, no Docker socket and no published ports. It is not on a separate internal network, and its runtime sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

Provision the abliterated organ's safetensors before training:

```bash
bash scripts/provision_organ_base.sh <safetensors-dir>
```

The script copies the weights to `/models/Qwen3.5-4B-abliterated` in the models volume and compares the sha256 of every file.

Voice alignment needs two independent opt-ins. The operator sets `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`, which Compose passes to `kaine-cycle`, `kaine-study` and `kaine-trainer` and which is empty unless set, and `[hypnos.voice_alignment].enabled` must be `true`.

Start the trainer service:

```bash
docker compose -f compose/kaine.yml --profile training up -d kaine-trainer
```

Jobs pass through the `kaine-trainer-jobs` volume. The cycle mounts it at its default `trainer_jobs_dir`, `state/hypnos/voice_align_jobs` (`/app/state/hypnos/voice_align_jobs`), and the study runner and the trainer mount it at `/trainer-jobs`; a study step that enables voice alignment sets `trainer_jobs_dir = "/trainer-jobs"` in its overlay.

## State, secrets and environment

### Named volumes

| Volume | Mounted at | Used by |
|---|---|---|
| `kaine-redis-data` | `/data` | `kaine-redis` |
| `kaine-qdrant-data` | `/qdrant/storage` | `kaine-qdrant` |
| `kaine-models` | `/models` (read-only except for `kaine-provision`) | model server, speech services, cycle, study, trainer |
| `kaine-state` | `/app/state` | cycle and Nexus: forks, preservation, individuation, world and self models, control state, audit and incident logs |
| `kaine-eval-data` | `/app/data/evaluation` | cycle and Nexus: run manifests under `runs/` and the evaluation observers' output |
| `kaine-trajectory` | `/app/data/workspace_trajectory` | cycle |
| `kaine-backups` | `/app/backups` | cycle: preservation bundles from the divergence monitor and the welfare response |
| `kaine-ignition` | `/app/data/ignition` | cycle: the film-aligned ignition log |
| `kaine-nexus-record` | `/app/data/nexus_record` | cycle: the local record of what Nexus displays |
| `kaine-studies` | `/app/studies` | study runner |
| `kaine-organ-adapters` | `/organ-adapters` | read-only on the model server, read-write on the cycle and the study runner |
| `kaine-trainer-jobs` | see [Voice alignment](#voice-alignment) | cycle, study runner, trainer |

`KAINE_DATA_ROOT=/app` is set on `kaine-nexus`, `kaine-cycle` and `kaine-study`, so growing data lands on these volumes even if the shared operator config sets a host `[storage].data_root`. Files in `kaine-state` keep owner-only permissions inside the container and survive `down` and `up`. The study runner mounts no `kaine-state`, perception tmpfs, `kaine-eval-data` or `kaine-trajectory`, because every step runs inside `/app/studies/<id>` and never touches a live being's volumes.

`config/profiles/` is part of the image, so `KAINE_PROFILE=thesis_test` resolves without a bind mount. The image also sets `ENV KAINE_GIT_SHA` from the `GIT_SHA` build argument, and the run manifest's `git_sha` falls back to it because containers carry no `.git`. The operator config and secrets are bind-mounted read-only and never copied into the image.

Redis runs with a `--maxmemory` ceiling from `KAINE_REDIS_MAXMEMORY` in `compose/.env` (default `4gb`) and `--maxmemory-policy noeviction`, so a full Redis halts the entity instead of silently dropping events. Size it to the bus: `python -m kaine.preboot` reports a "Bus budget" row that fails when measured stream sizes would not fit and warns when estimated sizes would not fit or the total passes 70% of the cap. A full study with every module enabled needs `KAINE_REDIS_MAXMEMORY=12gb` or more on hosts with the RAM. The quadlet unit reads the same variable from `compose/.env` and falls back to `4gb` when it is unset or empty. Restart Redis after changing it.

### Encryption and boot gates

The shipped config enables state encryption (`[security.state_encryption].enabled = true`). With `KAINE_STATE_KEY` empty, the cycle tries the kernel keyring and refuses to boot when no key is found. With `[preservation].require_encryption = true`, a research boot is refused at the start when encryption is required but off, in a container exactly as on the host.

| Variable | Purpose | Value on `kaine-cycle` |
|---|---|---|
| `KAINE_REDIS_PASSWORD` | bus password | required from `.env` |
| `KAINE_QDRANT_API_KEY` | vector-store key | required from `.env` |
| `KAINE_MODEL_SERVER_API_KEY` | organ server key | empty unless set |
| `KAINE_STATE_KEY` | encryption-at-rest key | empty unless set |
| `KAINE_CYCLE_OPERATOR_PRESENT` | operator-present gate | never defaulted |
| `KAINE_RESEARCH_MODE` | research gate | never defaulted |
| `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` | voice-alignment opt-in | never defaulted |

No boot-gate variable has a permissive default on `kaine-cycle` or `kaine-study`. The operator sets them explicitly, which keeps the first boot supervised.

## Compose profiles

The Compose profiles are `setup`, `cycle`, `study` and `training`:

- `setup` runs `kaine-provision`, the one-time model fetch.
- `cycle` runs `kaine-cycle`, the cognitive cycle.
- `study` runs `kaine-study`, the runner of the module-addition study (`python -m kaine.research.ignition_study`); see [The module-addition study](../15-experiments/ignition-study.md).
- `training` runs `kaine-trainer`, the voice-alignment trainer.

There are no `dev` or `research` profiles. `KAINE_RESEARCH_MODE` is a runtime gate.

The study runner passes its subcommand straight to the study module:

```bash
docker compose -f compose/kaine.yml --profile study run --rm kaine-study \
  init --study-id <id> --repo-root /app ...
docker compose -f compose/kaine.yml --profile study run --rm kaine-study \
  run --study-dir studies/<id>
```

`kaine-study` has no restart policy. An interrupted study resumes when you run it again, and after a failed step you run it with `--retry-failed`.

## Podman and quadlet

`podman compose -f compose/kaine.yml up -d` reads the same file. For a host that runs continuously, install the quadlet units:

```bash
bash scripts/install-quadlet.sh
```

The script writes the checkout's path into the units, and the units read their secrets from `compose/.env`. `kaine-cycle.container` has no `[Install]` section, so the entity never starts automatically, and the script never installs `kaine-cycle-unattended.container`. Quadlet has no trainer or study units, and its model-server unit does not use the launcher or the adapter volume, so `hot_swap_mode = "organ_adapter"` works only in Compose. See [A dedicated headless host](headless-host.md).

## Raw perception data is not persisted

No durable volume or bind mount captures raw audio or video. The cycle's perception scratch directory, `/app/state/perception`, is a RAM-backed tmpfs in both Compose and quadlet. `tests/test_container_deployment.py` fails if a named volume or a durable mount in the topology files covers a raw sense-data path.
