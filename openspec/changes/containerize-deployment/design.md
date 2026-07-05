# Design — containerized KAINE deployment

> **Status: DESIGN ONLY.** This is the design-of-record. No `Dockerfile`,
> `Containerfile`, compose, or Quadlet file is produced by this change. Every
> code block below is **illustrative** — it shows intent, not a deliverable.

## 1. Goals and constraints

Realize paper §11: "single-command deployment under Docker or Podman … without
manual service wiring … building on the event bus and vector store, which are
already containerized." The design is bound by hard constraints that
containerization MUST preserve:

1. **All-local, no cloud at runtime.** Models download at setup only; runtime
   reaches no network for weights.
2. **Zero raw-sense-data persistence** (load-bearing). Perception is processed in
   memory and released; raw A/V is never written. No volume/bind may create a
   persistence path for it.
3. **CPU-or-GPU portability.** CUDA primary; ROCm/XPU/MPS best-effort; CPU-only
   must work.
4. **No auto-start.** `run`/`up` must not boot an entity; first boot is operator-
   supervised; the shipped config is all-off with a guard test.
5. **Latency.** The live loop runs at 10 Hz processing / 3.333 Hz conscious-access;
   the topology must not add per-tick network hops that did not exist host-native
   (services already talked over loopback; containers talk over a compose bridge,
   same shape).

## 2. Service topology

One Compose project, one user-defined bridge network, every port mapped to
`127.0.0.1` only — matching the existing `compose/redis.yml` / `compose/qdrant.yml`
posture (loopback, mandatory secret, named volume, healthcheck).

```
compose/kaine.yml  (illustrative)
├── kaine-redis         (exists)   no-GPU   redis:7.2-alpine        127.0.0.1:6479
├── kaine-qdrant        (exists)   no-GPU   qdrant/qdrant:v1.18.0   127.0.0.1:6533
├── kaine-model-server  (new)      GPU      OpenAI-compat organ     127.0.0.1:11434
├── kaine-speaches      (new)      GPU      distil-Whisper STT      127.0.0.1:8000
├── kaine-chatterbox    (new)      GPU      Chatterbox TTS          127.0.0.1:8883
├── kaine-nexus         (new)      no-GPU   web UI (uvicorn)        127.0.0.1:8088
└── kaine-cycle         (new)      GPU      cognitive runtime       (no port)   [profile: cycle]
```

**The split that matters.** Host-native, Nexus (`python -m kaine.nexus`, uvicorn
on :8088) and the cycle (`python -m kaine.cycle`) are *already two processes*.
Keeping them as two services makes the no-auto-start invariant **structural**:

- `kaine-nexus` is always-up, safe, holds no entity — it bridges the bus read-only
  behind the metadata-only privacy boundary (paper §4.4).
- `kaine-cycle` carries `profiles: [cycle]`, so a default `docker compose up` /
  `podman ... up` brings up Redis, Qdrant, the model server, STT, TTS, and Nexus,
  but **not** the entity. Booting the cognitive cycle is the deliberate operator
  step: `docker compose --profile cycle run --rm kaine-cycle` (or the documented
  supervised `first-boot.sh` path), where the existing first-boot guard and the
  §6.2 unsupervised-research gate still apply unchanged.

`kaine-cycle` and `kaine-nexus` `depends_on` the data/model services with
`condition: service_healthy`. The cycle entrypoint runs the existing preflight
(service reachability + GPU headroom, `kaine/cycle/preflight.py`) before anything
cognitive, and the committed config still ships every module disabled.

## 3. One image, many hosts (the hardware-adaptivity decision)

The hard problem: the torch wheel is host/accelerator-specific (`scripts/install.py`
already picks the index per flavor — `cuda`→cu128, `rocm`→rocm6.2, `xpu`, `cpu`;
MPS uses default PyPI). A single image cannot contain all of them.

**Options considered**

| Option | Verdict |
|---|---|
| One fat image with all wheels | Rejected — multi-GB bloat, conflicting CUDA/ROCm userspace, impossible base image. |
| Runtime wheel download (pick on first boot) | Rejected — violates no-cloud-at-runtime and breaks reproducibility/air-gap. |
| **Build-arg flavor variants (chosen)** | One `Dockerfile`, `ARG FLAVOR`, selects base image + torch index at *build* time; reuse `_INDEX_BY_FLAVOR` verbatim. CPU + CUDA published first; ROCm/XPU experimental until smoke-tested on real HW (no pretend support). |

```dockerfile
# ILLUSTRATIVE — not a deliverable
ARG FLAVOR=cuda                 # cuda | cpu | rocm | xpu
FROM ${BASE_FOR_FLAVOR} AS build      # nvidia/cuda:12.8.*-cudnn-devel | python:3.12-slim | rocm/dev
ARG TORCH_INDEX                 # = scripts/install.py _INDEX_BY_FLAVOR[$FLAVOR]
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --index-url "${TORCH_INDEX}" torch  # exact spec from install.py
RUN /opt/venv/bin/pip install -e ".[<extras-for-enabled-modules>]"

FROM ${BASE_FOR_FLAVOR}-runtime AS runtime
COPY --from=build /opt/venv /opt/venv
RUN useradd -u 10001 kaine && mkdir -p /state /models && chown kaine /state /models
USER kaine
ENV HF_HOME=/models/hf TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
ENTRYPOINT ["/opt/venv/bin/python", "-m", "kaine.cycle"]   # nexus image overrides CMD
```

- The wheel-index logic is **lifted from `install.py`, not re-derived** — a single
  source of truth (a build step can shell out to `install.py --print-index $FLAVOR`
  or the implementer factors the map into an importable constant).
- `nexus` and `cycle` are the **same image**, different entrypoint — no second build.
- `TRANSFORMERS_OFFLINE=1` / `HF_HUB_OFFLINE=1` at runtime hard-enforce no-cloud.
- Devel base for build (CUDA extensions compile during pip), runtime base for the
  final stage to shrink the image.

## 4. GPU passthrough (Docker AND Podman)

The image cannot install host drivers; the host prerequisite is documented per
runtime. KAINE's two-GPU split (organ on the ~12 GB primary, vision encoder + TTS
on the ~8 GB secondary — paper §4.1) maps to per-service device pinning.

**Docker (NVIDIA Container Toolkit):**

```yaml
# ILLUSTRATIVE
kaine-model-server:
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, device_ids: ["0"], capabilities: [gpu] }]
kaine-cycle:
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, device_ids: ["1"], capabilities: [gpu] }]   # vision
```

**Podman (rootless, CDI):** generate the CDI spec once
(`nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`, or `~/.config/cdi` for
pure-rootless), then pin devices with `--device nvidia.com/gpu=0` /
`=1`, plus `--security-opt=label=disable` where SELinux requires it. Quadlet
`.container` files express the same with `AddDevice=nvidia.com/gpu=0`. CDI is the
recommended path and improves rootless compatibility.

**ROCm:** mount `/dev/kfd` + `/dev/dri`, add the `video`/`render` supplementary
groups; same per-service split on a two-GPU AMD host.

**CPU-only:** no device blocks; the CPU flavor image; always works, slower
(paper §4.1: "fully functional but substantially slower").

**Single-GPU host:** drop the secondary `device_ids` so organ + vision + TTS share
card 0 (paper §4.1: "secondary workloads move onto the primary card").

## 5. The organ-in-container vs on-host decision (key tradeoff)

`kaine/setup/model_server.py` runs the organ today as a **native long-running GPU
process** (Unsloth Studio's `llama-server` on NVIDIA, the unsloth-core build on
AMD) under operator-owned lifecycle, deliberately *not* a container — and on a CUDA
host it is the **same Unsloth toolchain** that the sleep-cycle voice-alignment
trainer uses, "so one server covers both inference and training" (paper §4.3).

| Approach | Pros | Cons |
|---|---|---|
| **Organ in a container** (`kaine-model-server`) | True single-command bring-up; matches §11 "complete instance"; clean GPU pin; reproducible. | The Unsloth/llama-server toolchain is heavy and CUDA-version-sensitive; containerizing it duplicates the trainer's GPU window; the trainer itself (Py3.13/cu130) must stay OUT, so on CUDA the "one server for inference + training" property is split. |
| **Organ on host, app in container** | Preserves the inference+training-shared server; lighter image; matches today. | Not single-command; operator still wires one host service; weakens the §11 promise. |

**Recommendation (for operator decision):** ship **both** as supported topologies.
Default `compose/kaine.yml` containerizes the organ with a generic OpenAI-compatible
server (llama.cpp-server or vLLM, GGUF/weights from the model volume, GPU pinned) so
a fresh researcher gets true one-command bring-up. Provide a documented
`organ=host` override (the container talks to `host.docker.internal:11434` /
`host.containers.internal:11434`) for operators who want the Unsloth shared
inference+training server — and that is the required topology whenever the
voice-alignment trainer is enabled, since the trainer is not containerized. **Open
question flagged for the operator below.**

## 6. No cloud at runtime — model provisioning

A **setup profile** (`profiles: [setup]` one-shot service, or a `make provision` /
script target) runs before first boot and:

1. Pulls every service image (pinned by digest).
2. Downloads every model weight into a shared `HF_HOME` named volume
   (`kaine-models`): the abliterated organ (reuse the existing `hf download`
   provisioning in `kaine/setup/`), distil-Whisper medium.en, Chatterbox voices,
   emotion2vec+, DINOv2-small, all-MiniLM-L6-v2.

At runtime `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` guarantee no fetch. Weights
live in a **volume, not an image layer** — best practice for multi-GB ML deps:
small image, shared cache across services, weights versioned as data not as image.
This honors the standing "all-local at runtime; setup-time downloads OK" rule.

## 7. State, volumes, welfare, and zero-raw-persistence

**Persistent (named volumes, survive `down`/`up`):**

| Volume | Backs | Notes |
|---|---|---|
| `kaine-redis-data` | bus stream | exists |
| `kaine-qdrant-data` | Mnemos/Empatheia vectors | exists |
| `kaine-models` | `HF_HOME`, `state/models` | provisioned at setup; read-mostly |
| `kaine-state` | `state/` runtime tree | the entity's life — see below |

`kaine-state` holds the CAL-gated **`state/forks`** (preserved beings, preservation
bundles, `merged_adapters`), individuation evidence, `state/cycle` (escalation,
incidents), `state/eidolon/self_model.json`, `state/phantasia/world_model.ckpt`,
`state/hypnos/adapters`, Praxis audit logs. Requirements:

- **Owner-only perms preserved inside the container.** The non-root `kaine` uid
  owns `/state`; the 0700/0600 posture the security work established holds inside
  the container (entrypoint `chown`/`chmod` on the mount as needed). Never baked
  into an image layer.
- **Encryption-at-rest.** `[security.state_encryption]` (AES-256-GCM) keyed by
  `KAINE_STATE_KEY` injected as a secret (env or compose/Podman secret, never in an
  image). Preservation `require_encryption = true` is fail-closed: a research boot
  is refused up-front if encryption is required but off — that gate is unchanged and
  must keep working in-container.
- **`.dockerignore`/`.containerignore`** excludes `state/`, `config/*.operator.toml`,
  `config/secrets.toml`, private voices, adapters, `.venv/`, caches — so none of it
  can enter a build context.

**Zero raw-sense-data persistence (load-bearing).** The perception feed
(`state/perception`, `state/audio_out`) and the live A/V apparatus are **not** given
a persistent volume for raw sense data; perception is processed in memory and
released. The design's invariant: there exists **no** volume or bind mount whose
purpose is to capture raw audio/video frames. Any perception scratch is `tmpfs`
(ephemeral, RAM-backed) or absent. This is asserted as a spec requirement and is a
container-build review checklist item.

**Welfare/audit:** incident and audit JSONL (Spot escalation, Praxis audit) live in
`kaine-state`, encrypted at rest when state encryption is on; they must survive
recreation (they are evidence).

## 8. Config and secret injection

- `config/kaine.toml` (committed, all-off) is in the image; the operator overlay
  `config/kaine.operator.toml` and `config/secrets.toml` are **bind-mounted
  read-only**, never COPYed.
- Secrets and gate flags via env / `.env` / compose-or-Podman secrets:
  `KAINE_REDIS_PASSWORD`, `KAINE_QDRANT_API_KEY`, `KAINE_MODEL_SERVER_API_KEY`,
  `KAINE_STATE_KEY`, and the boot-gate vars `KAINE_RESEARCH_MODE`,
  `KAINE_CYCLE_OPERATOR_PRESENT`, `KAINE_FIRST_BOOT_OPERATOR_PRESENT`,
  `KAINE_GPU_PREFLIGHT_APPROVED`, `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED`. The
  `cycle` service does **not** default any of the gate vars to a permissive value;
  the operator sets them explicitly, preserving supervised first boot.

## 9. Dev vs research profiles

- **`dev`** — single-surface Nexus, modules toggled in a local overlay, organ
  optionally host-side; for harness/UI work with no entity (matches the existing
  entity-free verification posture).
- **`research`** — the §6.2 unsupervised-research gate: divergence-triggered
  preservation enabled, welfare-protective response wired, full logging/admissibility
  active, and the preflight dry-run that preserves+revives a synthetic individual.
  `KAINE_RESEARCH_MODE=1` makes the cycle entrypoint refuse to boot (distinct exit
  code, no traceback) unless all four hold. Profiles change *which services and
  flags*, never the shipped-all-off default.

## 10. Podman parity (rootless + Quadlet)

- **`podman-compose` / `podman compose`** consumes the same `compose/kaine.yml` for
  dev/quick bring-up. Document rootless caveats: CDI for GPU, `:U`/`:Z` volume
  relabeling under SELinux, subuid/subgid for the non-root `kaine` uid, and
  loopback port mapping.
- **Quadlet** (`.container` + `.network` + optional `.pod`/`.image`/`.build` units)
  is the recommended **production single-host** path: containers become systemd
  services with native dependency ordering, logging, restart, and reboot survival —
  which suits a continuously-running research instrument better than a compose
  process. The cycle stays a manually-`start`ed unit (no `WantedBy` auto-start),
  preserving operator-supervised boot. Ship compose first; Quadlet as the
  production option.

## 11. Healthchecks and startup ordering

Reuse the existing pattern (redis/qdrant already declare healthchecks):
`kaine-model-server` (`GET /v1/models`), `kaine-speaches` (`/v1/models`),
`kaine-chatterbox` (`/get_predefined_voices`), `kaine-nexus` (`/health`,
`kaine/nexus/health.py`). `kaine-cycle` / `kaine-nexus` `depends_on:
condition: service_healthy`. The cycle's own preflight is the last gate before any
module work.

## 12. Phasing

- **D1** — the `kaine` image (CUDA + CPU flavors); `compose/kaine.yml` composing the
  existing redis/qdrant + `kaine-nexus` + `kaine-cycle`; cycle talks to host-native
  organ/STT/TTS first (smallest honest step). `.dockerignore` hygiene.
- **D2** — containerize the three GPU services into the compose; GPU reservations;
  the two-GPU device split; the `organ=host` override documented.
- **D3** — the setup-phase model provisioning + the state/secret volume model +
  zero-raw-persistence assertion; one-command `up` (minus the cycle).
- **D4** — Podman Quadlet units; ROCm/XPU image flavors (experimental); a CI image-
  build smoke (build + `--version`/preflight only, NO entity boot); present-tense docs.

## 13. Risks and open questions

**Risks**

- Image size (CUDA + torch + cuDNN is multi-GB even without weights) — multi-stage,
  runtime base, weights in a volume.
- GPU-in-container portability varies by host/driver/runtime — document prerequisites
  per runtime; CPU flavor is the always-works fallback; mark ROCm/XPU experimental
  until real-HW smoke (no pretend support).
- Latency: the compose bridge adds a hop vs pure loopback; expected negligible at
  10 Hz, but the implementer must measure the conscious-access path before declaring
  parity.
- Multi-vendor honesty: ship CUDA+CPU first; never claim untested vendor support.

**Open questions (operator to decide)**

1. **Organ default: in-container or on-host?** (§5) The default-containerized organ
   gives true one-command bring-up but does not preserve the Unsloth "one server for
   inference + training" property; `organ=host` does, and is *required* when the
   voice-alignment trainer is enabled. Recommend default-containerized + documented
   host override; confirm.
2. **Compose vs Quadlet as the *advertised* path.** Compose is the familiar
   single-command story the paper names; Quadlet is the better continuously-running
   production substrate. Recommend compose-first, Quadlet-for-production; confirm
   priority.
3. **Does the public reference image ship CPU-only by default** (universally runnable,
   slow) **and require an explicit CUDA build**, or ship both tagged? Recommend both
   tagged (`kaine:cpu`, `kaine:cuda`), CPU as the documented default for a fresh
   clone.

## Sources

- Docker Compose GPU support — https://docs.docker.com/compose/how-tos/gpu-support/
- NVIDIA Container Toolkit, CDI support — https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html
- Podman GPU container access (CDI, rootless) — https://podman-desktop.io/docs/podman/gpu
- "How to Use GPU Passthrough with Podman" — https://oneuptime.com/blog/post/2026-03-18-use-gpu-passthrough-podman/view
- "Make systemd better for Podman with Quadlet" (Red Hat) — https://www.redhat.com/en/blog/quadlet-podman
- podman-systemd.unit (Quadlet reference) — https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html
- Docker + Hugging Face local hosting (model volumes) — https://www.docker.com/blog/llm-docker-for-local-and-hugging-face-hosting/
- Shared HF cache (`HF_HOME`) best practice — https://benjijang.com/posts/2024/01/shared-hf-cache/
- PyTorch + CUDA 12.8 Docker setup — https://www.runpod.io/articles/guides/docker-setup-pytorch-cuda-12-8-python-3-11
