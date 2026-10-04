# Containers

KAINE's container deployment brings up the supporting services, the dashboard, the cognitive cycle, the study runner, and the voice-alignment trainer as one stack. This page is for operators who want to build, provision, and run KAINE with Docker or Podman. It covers the container topology, how to start services without accidentally booting an entity, and how state, secrets, and gates are handled.

With no profile selected, the loader applies the base-thesis `thesis_test` profile automatically. `thesis_test` sets the `[modules]` flags (`soma`, `chronos`, `topos`, `audition`, `lingua`, `thymos` on; everything else off, including `phantasia`, `hypnos`, `nous`, `mnemos`, `perception`, `mundus`), `[perception_feed].mode = "seeded"` with seed 0, `[topos].foveation = true`, `[audition].transcription_enabled = false` with `general_audition = true`, and `[volition]` policy `self_initiated_report`, `drive_initiative = false`, `sig_expiry_s = 300.0`. Every other value — organ model, Whisper model, encryption, rates, Phantasia backend, CfC backend, and so on — comes from the shipped `config/kaine.toml`. The shipped `config/kaine.toml` sets `[perception_feed].mode = "off"`, `[hypnos.voice_alignment].hot_swap_mode = "manual"` and `trainer_backend = "in_process"`, and `[security.state_encryption].enabled = true`.

`config/kaine.operator.toml` merges last and wins, and the first-run wizard (`python -m kaine.setup`) always writes a full `[modules]` table there, so after the wizard runs its module choices replace the profile's. The wizard's own defaults are `soma`, `chronos`, `thymos`, `eidolon`, `mnemos`, and `lingua` on, `topos` and `audition` off.

## Topology

| Service | Role | Endpoint | GPU |
|---|---|---|---|
| `kaine-redis` | event bus (Redis Streams) | `127.0.0.1:6479` | no |
| `kaine-qdrant` | memory + social vectors | `127.0.0.1:6533` | no |
| `kaine-model-server` | OpenAI-compatible language organ | `127.0.0.1:11434` | card 0 |
| `kaine-speaches` | speech-to-text (distil-Whisper) | `127.0.0.1:8000` | **CPU** |
| `kaine-chatterbox` | text-to-speech | `127.0.0.1:8883` | card 1 |
| `kaine-nexus` | web UI (uvicorn) | `127.0.0.1:8088` | no |
| `kaine-cycle` | the cognitive runtime (the entity) | none | card 1 |
| `kaine-study` | the module-ignition study runner (`--profile study`) | none | card 1 |
| `kaine-trainer` | voice-alignment trainer service (DPO+QLoRA → GGUF) | none | the organ's GPU |

By default `kaine-chatterbox` uses the image `kaine-chatterbox:local` and has no upstream image. A plain `docker compose -f compose/kaine.yml up` fails unless you build the image first or set `KAINE_CHATTERBOX_IMAGE` to an available image.

Open `http://127.0.0.1:8088/diagnostics/` on the host to reach `kaine-nexus`. By default `[nexus].access` is `"open"`, so no token or sign-in is required. To require a token, add a tailnet host, or make the dashboard read-only, set the variables that `kaine-nexus` actually reads from `compose/.env`: `KAINE_NEXUS_ACCESS`, `KAINE_NEXUS_TOKEN`, `KAINE_NEXUS_EXTRA_HOSTS`, and `KAINE_NEXUS_HOST_PORT`. In code `kaine-nexus` also reads `KAINE_NEXUS_HOST`, `KAINE_NEXUS_PORT`, `KAINE_NEXUS_CONVERSATION_ENABLED`, `KAINE_NEXUS_READ_ONLY`, `KAINE_NEXUS_NON_LOOPBACK_ALLOWED`, and `KAINE_NEXUS_ALLOWED_ORIGINS`, but Compose does not interpolate those from `.env`; `NON_LOOPBACK_ALLOWED` is hard-coded to `"1"`, `ALLOWED_ORIGINS` is hard-coded to the loopback origins, and `READ_ONLY` comes only from the untracked overlay `compose/kaine.study-view.local.yml`. Setting the rest in `.env` has no effect. `compose/.env.example` lists none of the Nexus access variables. Host and Origin checks always apply, and `/` redirects to `/diagnostics/` when conversation is off. See [Nexus, the dashboard](../05-nexus.md).

`kaine-nexus`, `kaine-cycle`, and `kaine-study` are the same runtime image with different commands. `kaine-trainer` uses the separate `kaine:trainer-<flavor>` image.

## The images

The [Dockerfile](../../Dockerfile) builds two targets:

- `runtime` — the default image, `kaine:<flavor>`.
- `trainer` — `kaine:trainer-<flavor>`, used by the voice-alignment service.

The `FLAVOR` build-arg selects the accelerator-correct PyTorch build from `kaine/wheel_index.py`, run standalone before the package is installed (`--image-index <flavor>` for the index, `--torch-spec` for the torch requirement):

```bash
# CUDA runtime (default)
docker build -t kaine:cuda .

# CPU runtime (always works)
docker build -t kaine:cpu \
  --build-arg FLAVOR=cpu \
  --build-arg BUILD_BASE=python:3.12-slim \
  --build-arg RUNTIME_BASE=python:3.12-slim .

# Trainer image
docker build --target trainer -t kaine:trainer-cuda .
```

ROCm and XPU flavors exist but are experimental until validated on real hardware; CPU is the always-works fallback.

## Provision models once

Weights are provisioned into the shared `kaine-models` volume before first boot; they never live in an image layer:

```bash
cp compose/.env.example compose/.env      # then fill in the secrets
docker compose -f compose/kaine.yml --profile setup run --rm kaine-provision
```

This runs `python -m kaine.setup.provision`, which downloads the abliterated organ, InternVideo-Next (the default vision world model), all-MiniLM, and `emotion2vec+`. It also downloads DINOv2-small only if selected; distil-Whisper and Chatterbox only if their speech backends are selected. The sherpa-onnx speech archives — Kokoro (which bundles the espeak-ng data inside it), Moonshine, and any other spoken models Audition or Vox select — are fetched only when a module selects `"sherpa_onnx"` and the operator passes `--speech-models` or sets `KAINE_PROVISION_SPEECH_MODELS=1` after the plan shows each archive's name, size, and licence.

This is the only phase that fetches models. Runtime sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

## Bring up the supporting services

```bash
docker compose -f compose/kaine.yml up -d
```

This starts the bus, vector store, model server, speech services, and Nexus. It does **not** start the entity: `kaine-cycle` has `profiles: [cycle]`, so a plain `up` never runs it. A bare `docker run kaine:<flavor>` also never starts an entity, because the cycle refuses to boot without the operator gate.

CPU-only or single-GPU hosts overlay a profile file:

```bash
# CPU-only
KAINE_FLAVOR=cpu docker compose -f compose/kaine.yml -f compose/kaine.cpu.yml up -d

# Single GPU (organ + vision + TTS share card 0)
docker compose -f compose/kaine.yml -f compose/kaine.single-gpu.yml up -d
```

The device map is `[hardware.devices]`, written by `python -m kaine.setup`. It produces `KAINE_ORGAN_GPU` and `KAINE_VISION_GPU`. `KAINE_TRAINER_GPU` is a Compose default that falls back to the organ card, not part of the setup-written map. `kaine.cpu.yml` and `kaine.single-gpu.yml` do not override `kaine-study` or `kaine-trainer`, so both still reserve card `${KAINE_VISION_GPU:-1}`; disable or adjust them if that card does not exist.

## Start the cognitive cycle

Booting the cycle is deliberate. The first-boot guard and the unsupervised-research gate apply unchanged:

```bash
KAINE_CYCLE_OPERATOR_PRESENT=1 \
  docker compose -f compose/kaine.yml --profile cycle run --rm kaine-cycle
```

See [First boot](../04-getting-started/first-boot.md) for the operator-supervised boot flow. `KAINE_RESEARCH_MODE=1` makes the cycle refuse to boot unless all five conditions of the research gate hold, including encryption. Compose does not pass `KAINE_CYCLE_UNATTENDED` to `kaine-cycle`; select unattended mode through `[cycle].supervision_mode` in a bind-mounted overlay.

## GPU passthrough

**Docker (NVIDIA Container Toolkit).** `compose/kaine.yml` reserves devices through `deploy.resources.reservations.devices`: the organ on card 0, vision and TTS on card 1. Install the NVIDIA Container Toolkit on the host first.

**Podman (rootless, CDI).** Generate the CDI spec once, then the Quadlet `AddDevice=nvidia.com/gpu=N` lines take effect:

```bash
nvidia-ctk cdi generate --output=$HOME/.config/cdi/nvidia.yaml
```

**ROCm (AMD, experimental).** Overlay `compose/kaine.rocm.yml`, which mounts `/dev/kfd` and `/dev/dri` and adds the `video` and `render` groups.

## Where the organ runs

By default the organ runs inside `kaine-model-server`, using `docker/organ-launcher.sh` as its entrypoint, for true one-command bring-up. The in-container organ unloads after `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` idle seconds (default 600) and reloads on the next request. If you override `KAINE_MODEL_SERVER_CMD`, pass `--sleep-idle-seconds` yourself.

Voice alignment can still run in the `kaine-trainer` service, so an in-container organ and a containerized trainer can work together without a host-native server. For `hot_swap_mode = "organ_adapter"` — replacing the active LoRA without restarting the organ — mount `kaine-organ-adapters` at `organ_adapters_dir` (default `/organ-adapters`). This mode is only available in Compose; the Quadlet model-server unit does not use the launcher or adapters.

To use a host-native Unsloth server that shares one process for inference and training, overlay `compose/kaine.organ-host.yml` and point `[lingua].chat_url` at `http://host.docker.internal:11434/v1` (use `host.containers.internal` on Podman). When `model_server` is declared as a shared service, KAINE forces `[hypnos.voice_alignment].hot_swap_mode = "manual"` because the cycle cannot orchestrate a foreign server's LoRA lifecycle. A host-native server used on its own does not trigger that override.

## Voice alignment

Voice alignment uses the `kaine-trainer` service, gated behind the compose profile `training`. The trainer container is isolated from entity state, the Docker socket, and host ports. It is not placed on a separate internal network, but runtime sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

Provision the abliterated organ's HuggingFace safetensors before training:

```bash
bash scripts/provision_organ_base.sh <safetensors-dir>
```

That copies the weights to `/models/Qwen3.5-4B-abliterated` inside the models volume and verifies every file's sha256.

Voice alignment has two independent opt-ins: the operator must set `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` for `kaine-cycle`, `kaine-study`, and `kaine-trainer` (Compose passes `${KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED:-}`, which is empty unless the operator sets it), and the config gate `[hypnos.voice_alignment].enabled` must be `true`.

Start the trainer service:

```bash
docker compose -f compose/kaine.yml --profile training up -d kaine-trainer
```

Mount `kaine-models` read-only and `kaine-trainer-jobs` read-write at the paths configured by `trainer_jobs_dir`. The cycle's default for `trainer_jobs_dir` is `state/hypnos/voice_align_jobs`; the study and trainer containers use `/trainer-jobs`. For `hot_swap_mode = "organ_adapter"` also mount `kaine-organ-adapters` at `organ_adapters_dir`.

## State, secrets, and environment

### Named volumes

Persistent named volumes:

- `kaine-redis-data`
- `kaine-qdrant-data`
- `kaine-models` (read-mostly)
- `kaine-state` — the entity's life: CAL-gated forks, preservation bundles, individuation, world/self models, control state, audit/incident logs
- `kaine-eval-data` — `/app/data/evaluation` on both the cycle and Nexus: run manifests under `runs/` plus every evaluation observer's output
- `kaine-backups` — `/app/backups`, preservation bundles from the divergence monitor and welfare response
- `kaine-ignition` — `/app/data/ignition`, the film-aligned ignition log
- `kaine-trajectory` — `/app/data/workspace_trajectory`
- `kaine-nexus-record`
- `kaine-studies`
- `kaine-organ-adapters`
- `kaine-trainer-jobs`

`KAINE_DATA_ROOT=/app` is set on the `kaine-nexus`, `kaine-cycle`, and `kaine-study` services. `kaine-state` keeps owner-only (`0700`/`0600`) permissions inside the container and survives `down`/`up`. Nothing the run produces lives on the ephemeral container layer.

Only `kaine-redis`, `kaine-qdrant`, `kaine-cycle`, `kaine-study`, `kaine-trainer`, and `kaine-provision` use the shared `json-file` rotation anchor (50 MB × 3 files). `kaine-model-server`, `kaine-speaches`, `kaine-chatterbox`, and `kaine-nexus` do not. `config/profiles/` is baked into the image, so `KAINE_PROFILE=thesis_test` resolves in-container without a bind mount. The image also bakes `ARG GIT_SHA` into `ENV KAINE_GIT_SHA`, which the run manifest's `git_sha` falls back to (containers carry no `.git`). Operator config, secrets, and adapters are bind-mounted read-only, never copied into the image. There is no voices bind mount in `compose/kaine.yml`; `kaine-organ-adapters` is a named volume that is read-only on `kaine-model-server` and read-write on `kaine-cycle` and `kaine-study`.

Redis runs with a `--maxmemory` ceiling set by `KAINE_REDIS_MAXMEMORY` in `compose/.env` (default `4gb`) and `noeviction`. A full Redis halts the entity rather than silently dropping events. Size it to the bus: `python -m kaine.preboot` reports a "Bus budget" row that FAILS when measured stream sizes would not fit, and WARNS when only estimated sizes push it over or it is above 70% of the cap. A full study with every module enabled needs `KAINE_REDIS_MAXMEMORY=12gb` or more on hosts with the RAM. The Quadlet unit reads the same variable from `compose/.env`, and an unset or empty value falls back to `4gb`; restart Redis after changing it.

### Encryption and boot gates

The shipped config already enables state encryption (`[security.state_encryption].enabled = true`), so an empty `KAINE_STATE_KEY` refuses boot. Preservation `require_encryption = true` is fail-closed: a research boot is refused up-front if encryption is required but off, in-container exactly as host-native.

| Variable | Purpose | Default on `kaine-cycle` |
|---|---|---|
| `KAINE_REDIS_PASSWORD` | event-bus auth | required (from `.env`) |
| `KAINE_QDRANT_API_KEY` | vector-store auth | required (from `.env`) |
| `KAINE_MODEL_SERVER_API_KEY` | organ server auth | empty |
| `KAINE_STATE_KEY` | encryption-at-rest key | empty — boot refusal |
| `KAINE_CYCLE_OPERATOR_PRESENT` | first-boot gate | **never defaulted** |
| `KAINE_RESEARCH_MODE` | unsupervised-research gate | **never defaulted** |

No boot-gate variable is defaulted to a permissive value on the `kaine-cycle` service. The operator sets them explicitly, preserving supervised first boot.

### Nexus overrides

`kaine-nexus` reads `KAINE_NEXUS_ACCESS`, `KAINE_NEXUS_TOKEN`, `KAINE_NEXUS_EXTRA_HOSTS`, and `KAINE_NEXUS_HOST_PORT` from `compose/.env`. The other variables that the code accepts — `KAINE_NEXUS_HOST`, `KAINE_NEXUS_PORT`, `KAINE_NEXUS_CONVERSATION_ENABLED`, `KAINE_NEXUS_READ_ONLY`, `KAINE_NEXUS_NON_LOOPBACK_ALLOWED`, and `KAINE_NEXUS_ALLOWED_ORIGINS` — are hard-coded or supplied through overlay files, so setting them in `.env` has no effect.

## Compose profiles

The real compose profiles are `setup`, `cycle`, `study`, and `training`:

- `setup` — `kaine-provision`, the one-time model fetch.
- `cycle` — `kaine-cycle`, the cognitive runtime.
- `study` — `kaine-study`, the module-ignition study runner; see [The module-ignition study](../15-experiments/ignition-study.md).
- `training` — `kaine-trainer`, the voice-alignment trainer service.

There are no `dev` or `research` compose profiles. `KAINE_RESEARCH_MODE` is a runtime gate, not a profile.

## Podman and Quadlet

`podman compose -f compose/kaine.yml up -d` consumes the same file. For a continuously-running research instrument, install the Quadlet units with:

```bash
bash scripts/install-quadlet.sh
```

This writes the checkout's path into the units; secrets reach them from `compose/.env`. The `kaine-cycle` unit has no `[Install]` section, so the entity is never auto-started. Quadlet has no trainer or study units, and its model-server unit does not use the launcher or adapter volume, so `hot_swap_mode = "organ_adapter"` is Compose-only. See [A dedicated headless host](headless-host.md) for more.

## Raw perception data is not persisted

No durable volume or bind mount captures raw audio or video frames. Perception scratch, if any, is RAM-backed `tmpfs`. This invariant is enforced by `tests/test_container_deployment.py`, which fails if any topology file declares a persistence path for raw sense data.
