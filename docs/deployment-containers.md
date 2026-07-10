# Containerized deployment (Docker / Podman)

KAINE ships a single container image and a declarative topology that stand up a
full local instance — event bus, vector store, model server, speech-to-text,
text-to-speech, and the Nexus web UI — without manual per-service wiring, and
**without ever auto-starting an entity**. The cognitive cycle is a separate,
operator-invoked, profile-gated step.

Everything binds to loopback. Models download once at setup; runtime reaches no
network for weights. Entity state lives in named volumes with owner-only
permissions and optional encryption-at-rest. No volume or bind mount ever
captures raw audio or video — perception is processed in memory and released.

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

`kaine-nexus` and `kaine-cycle` are the **same image**, different command.
Speaches runs on CPU by design — running it on GPU triggers a cuDNN crash when
the secondary GPU also serves TTS.

## One image, many hosts

The accelerator-correct PyTorch build is selected at **build time** from the
`FLAVOR` build-arg, which reuses `scripts/install.py`'s wheel-index mapping
verbatim (`install.py --print-index <flavor>`):

```bash
# CUDA (default, published):
docker build -t kaine:cuda .

# CPU (universally runnable, published):
docker build -t kaine:cpu \
  --build-arg FLAVOR=cpu \
  --build-arg BUILD_BASE=python:3.12-slim \
  --build-arg RUNTIME_BASE=python:3.12-slim .
```

ROCm and XPU flavors exist but are **experimental** until validated on real
hardware; CPU is the always-works fallback.

## Setup — provision all models once

Weights are provisioned into the shared `kaine-models` volume before first boot;
they never live in an image layer:

```bash
cp compose/.env.example compose/.env      # then fill in the secrets
docker compose -f compose/kaine.yml --profile setup run --rm kaine-provision
```

This runs `python -m kaine.setup.provision`, which downloads the abliterated
organ, distil-Whisper, Chatterbox, emotion2vec+, DINOv2-small, and all-MiniLM
via real `hf download`. It is the **only** phase that fetches models; runtime
sets `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`.

## Bring-up (no entity)

```bash
docker compose -f compose/kaine.yml up -d
```

This starts everything **except** the cycle. `kaine-cycle` carries
`profiles: [cycle]`, so a plain `up` never starts an entity. A bare
`docker run kaine:<flavor>` also never starts an entity: the cycle refuses to
boot without the operator gate.

CPU-only or single-GPU hosts overlay a profile file:

```bash
# CPU-only:
KAINE_FLAVOR=cpu docker compose -f compose/kaine.yml -f compose/kaine.cpu.yml up -d
# Single GPU (organ + vision + TTS share card 0):
docker compose -f compose/kaine.yml -f compose/kaine.single-gpu.yml up -d
```

## Boot the cycle (operator-supervised)

Booting the cognitive cycle is deliberate. The application-layer first-boot
guard and the unsupervised-research gate still apply unchanged:

```bash
KAINE_CYCLE_OPERATOR_PRESENT=1 \
  docker compose -f compose/kaine.yml --profile cycle run --rm kaine-cycle
```

## GPU passthrough

**Docker (NVIDIA Container Toolkit).** The compose file reserves devices via
`deploy.resources.reservations.devices` — organ on card 0, vision + TTS on
card 1. Install the NVIDIA Container Toolkit on the host first.

**Podman (rootless, CDI).** Generate the CDI spec once, then the Quadlet
`AddDevice=nvidia.com/gpu=N` lines take effect:

```bash
nvidia-ctk cdi generate --output=$HOME/.config/cdi/nvidia.yaml
```

**ROCm (AMD, experimental).** Overlay `compose/kaine.rocm.yml`, which mounts
`/dev/kfd` + `/dev/dri` and adds the `video`/`render` groups.

## Organ in-container vs on-host

By default the organ runs in `kaine-model-server` (a generic OpenAI-compatible
GGUF server) for true one-command bring-up. To use a **host-native** Unsloth
server that shares one process for inference and training — **required whenever
the voice-alignment trainer is enabled**, since the trainer is not
containerized — overlay `compose/kaine.organ-host.yml` and point
`[lingua].chat_url` at `http://host.docker.internal:11434/v1`
(`host.containers.internal` on Podman).

## State, secrets, and the env/gate-var matrix

Persistent named volumes: `kaine-redis-data`, `kaine-qdrant-data`,
`kaine-models` (read-mostly), and `kaine-state` (the entity's life — CAL-gated
forks, preservation bundles, individuation, world/self models, control state,
audit/incident logs). `kaine-state` keeps owner-only (0700/0600) permissions
inside the container and survives `down`/`up`. Operator config, secrets, private
voices, and adapters are **bind-mounted read-only**, never copied into the image.

Enable encryption-at-rest by setting `[security.state_encryption].enabled = true`
and injecting `KAINE_STATE_KEY`. Preservation `require_encryption = true` is
fail-closed: a research boot is refused up-front if encryption is required but
off — in-container exactly as host-native.

| Variable | Purpose | Default on cycle service |
|---|---|---|
| `KAINE_REDIS_PASSWORD` | event-bus auth | required (from `.env`) |
| `KAINE_QDRANT_API_KEY` | vector-store auth | required (from `.env`) |
| `KAINE_MODEL_SERVER_API_KEY` | organ server auth | empty |
| `KAINE_STATE_KEY` | encryption-at-rest key | empty (set to enable) |
| `KAINE_CYCLE_OPERATOR_PRESENT` | first-boot gate | **never defaulted** |
| `KAINE_RESEARCH_MODE` | unsupervised-research gate | **never defaulted** |

No boot-gate variable is defaulted to a permissive value on the `kaine-cycle`
service. The operator sets them explicitly, preserving supervised first boot.

## Dev vs research profiles

- **dev** — single-surface Nexus, modules toggled in a local overlay, organ
  optionally host-side; for harness/UI work with no entity.
- **research** — the unsupervised-research gate: divergence-triggered
  preservation, welfare-protective response, full logging/admissibility, and the
  preserve→revive dry-run. `KAINE_RESEARCH_MODE=1` makes the cycle refuse to boot
  (distinct exit code, no traceback) unless all four hold.

Neither profile changes the shipped-all-off default.

## Podman + Quadlet (production)

`podman compose -f compose/kaine.yml up -d` consumes the same file. For a
continuously-running research instrument, install the Quadlet units in
`quadlet/` (systemd services with dependency ordering, restart, reboot
survival). The `kaine-cycle` unit has **no `[Install]` section** — the entity is
never auto-started. See `quadlet/README.md`.

## Zero raw-sense-data persistence

No durable volume or bind mount captures raw A/V frames. Perception scratch, if
any, is RAM-backed `tmpfs`. This invariant is enforced by
`tests/test_container_deployment.py`, which fails if any topology file declares a
persistence path for raw sense data.
