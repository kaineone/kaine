# Containerize the KAINE deployment (Docker / Podman)

## Why

The paper names this as planned future work and as a precondition for the public
release of the reference implementation. §11 (Future work):

> "Full containerization of the system for single-command deployment under Docker
> or Podman, so a researcher can stand up a complete instance without manual
> service wiring, planned before the public release of the reference
> implementation and building on the event bus and vector store, which are
> already containerized."

§4.3 (Software stack) confirms the starting point: "Redis, containerized, for the
event bus. Qdrant, containerized, for memory and agent profiles." Two of the
long-running services already ship as containers (`compose/redis.yml`,
`compose/qdrant.yml`, with a matching `compose/.env.example`); everything else —
the OpenAI-compatible model server, speech-to-text, text-to-speech, the Nexus web
UI, and the cognitive cycle itself — runs host-native today via `scripts/install.py`
(venv + per-host torch wheel) and per-service bootstraps. A researcher therefore
wires five-plus processes by hand.

This change brings the existing `containerize-deployment` plan up to date with the
merged work (unified inference on a single OpenAI-compatible endpoint — Ollama is
gone; the Nexus web UI is a *separate* `python -m kaine.nexus` uvicorn process from
the `python -m kaine.cycle` cognitive runtime) and turns it into a complete,
implementable design that realizes the §11 statement: one declarative topology
that stands up a full local instance, on Docker **or** Podman, on CUDA / ROCm / CPU,
without manual service wiring — and without ever auto-starting an entity.

**This is a DESIGN-ONLY change.** It ships no `Dockerfile`, no `Containerfile`, no
compose/Quadlet files. Snippets in `design.md` are illustrative only. The output
is the OpenSpec artifacts; implementation is a later, separately-approved change.

## What Changes (design-only scope)

- **Service topology of record.** A single Compose project (and an equivalent
  rootless-Podman Quadlet layout) composing the two existing containers
  (`kaine-redis` :6479, `kaine-qdrant` :6533) with the rest of the stack:
  `kaine-model-server` (OpenAI-compatible organ, :11434), `kaine-speaches`
  (STT, :8000), `kaine-chatterbox` (TTS, :8883), `kaine-nexus` (web UI, :8088),
  and `kaine-cycle` (the cognitive runtime, no port). Every port loopback-only.
- **A two-service split that makes "no auto-start" structural.** `kaine-nexus`
  (always-up, safe, no entity) is separated from `kaine-cycle` (the entity).
  Default `up` brings up everything *except* the cycle; the cycle is a deliberate,
  operator-invoked, profile-gated step. The shipped image still ships every module
  disabled with the guard test intact.
- **One image, many hosts.** A multi-stage `kaine` image selecting the
  accelerator-correct torch wheel at build time via a `FLAVOR` build-arg that
  reuses `scripts/install.py`'s existing `_INDEX_BY_FLAVOR` mapping (cuda cu128 /
  rocm6.2 / xpu / cpu; MPS = default PyPI). `kaine-nexus` and `kaine-cycle` share
  this one image with different entrypoints. Ship CUDA + CPU first; ROCm/XPU
  marked experimental until validated on real hardware.
- **GPU passthrough for both runtimes.** NVIDIA Container Toolkit device
  reservations for Docker (`deploy.resources.reservations.devices` / `--gpus`) and
  CDI (`--device nvidia.com/gpu=...`) for rootless Podman; ROCm via `/dev/kfd` +
  `/dev/dri`; the two-GPU split (organ→cuda:0, vision/TTS→cuda:1) expressed as
  per-service `device_ids`. CPU-only is the always-works fallback.
- **Model weights are volumes, never image layers.** A one-shot setup profile
  downloads all weights (abliterated organ, distil-Whisper, Chatterbox, emotion2vec,
  DINOv2, MiniLM) into a shared `HF_HOME` named volume at **setup time**; runtime
  reaches no network for models. This keeps the image small and honors all-local-
  at-runtime.
- **State, welfare, and zero-raw-persistence model.** Named volumes for the things
  that must survive recreation (CAL-gated `state/forks`, preservation bundles,
  individuation, `state/models`, world-model checkpoints, self-model, Qdrant data,
  audit/incident logs); owner-only perms preserved inside the container; encryption-
  at-rest (`KAINE_STATE_KEY` / `[security.state_encryption]`) wired through. The
  load-bearing **zero raw-sense-data persistence** invariant is preserved: no
  bind/volume path that could capture raw A/V exists, and the perception feed
  directory is never persisted.
- **Config and secret injection.** `config/kaine.operator.toml` and
  `config/secrets.toml` bind-mounted read-only (never COPYed); secrets and gate
  flags (`KAINE_REDIS_PASSWORD`, `KAINE_QDRANT_API_KEY`, `KAINE_MODEL_SERVER_API_KEY`,
  `KAINE_STATE_KEY`, `KAINE_RESEARCH_MODE`, `KAINE_CYCLE_OPERATOR_PRESENT`,
  `KAINE_GPU_PREFLIGHT_APPROVED`, …) via env/`.env`.
- **Dev vs research profiles.** A `dev` profile (single-surface Nexus, modules
  toggled locally) and a `research` profile (the unsupervised-research gate +
  autonomous safety net), neither of which changes the shipped-all-off default.
- A new `containerized-deployment` capability spec captures the requirements.

## Impact

- **Affected systems:** packaging/install path (`scripts/install.py`,
  `scripts/*-bootstrap.sh`, `kaine/setup/model_server.py`), the `compose/`
  directory, the Nexus and cycle entrypoints (`kaine/nexus/__main__.py`,
  `kaine/cycle/__main__.py`), and operator docs. No runtime cognition code changes.
- **The volume/state model** becomes explicit: a clear persistent-vs-ephemeral
  split with the CAL-gated preserved-beings volume and encryption-at-rest, and an
  enforced absence of any raw-perception persistence path.
- **The supervised-boot invariant** is baked into the topology: `docker run` /
  `podman run` of the image, and a plain `compose up`, never start an entity; the
  cycle is a separate operator-invoked step gated by the same first-boot guard and
  research gate that exist today.
- **Out of scope:** the Unsloth Studio voice-alignment trainer (separate
  Py3.13/cu130 env, stays out of the runtime image); BOINC / distributed-substrate
  packaging (separate `distributed-substrate` change that *consumes* this image);
  any cloud runtime; and any actual build artifacts (design-only).
