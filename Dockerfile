# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
#
# One image, many hosts. A single multi-stage build produces the KAINE runtime
# image for both `kaine-cycle` (the cognitive runtime) and `kaine-nexus` (the
# web UI) — same image, different CMD. The accelerator-correct PyTorch wheel is
# selected at BUILD time from a FLAVOR build-arg that reuses scripts/install.py's
# single source of truth (`install.py --print-index <flavor>`), never re-derived
# here. See openspec/changes/containerize-deployment/design.md §3.
#
#   FLAVOR=cuda  (default, published)     nvidia/cuda devel→runtime bases
#   FLAVOR=cpu   (published, always-works) python:3.12-slim base
#   FLAVOR=rocm  (EXPERIMENTAL — unvalidated on real HW)
#   FLAVOR=xpu   (EXPERIMENTAL — unvalidated on real HW)
#
# Build (CUDA, default):
#   docker build -t kaine:cuda .
# Build (CPU, universally runnable):
#   docker build -t kaine:cpu \
#     --build-arg FLAVOR=cpu \
#     --build-arg BUILD_BASE=python:3.12-slim \
#     --build-arg RUNTIME_BASE=python:3.12-slim .
#
# Model weights are NEVER baked into a layer — they live in the kaine-models
# volume, provisioned at setup time (design §6). This image reaches no network
# for models at runtime (HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE below).

# ---- build-time args (defaults target the published CUDA flavor) ----
ARG FLAVOR=cuda
# Devel base compiles CUDA extensions during pip; runtime base shrinks the final
# image. Override both for the CPU/ROCm/XPU flavors (see header).
ARG BUILD_BASE=nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04
ARG RUNTIME_BASE=nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04
# Extras installed into the image. Keep lean by default; perception/vision/audio
# extras are opt-in at build time (they pull cv2/av/funasr). The abliterated
# organ, STT/TTS models, and embedders are provisioned to the volume, not here.
ARG KAINE_EXTRAS=".[test]"

# =========================================================================
# Stage 1 — build: create the venv, install the flavor-correct torch, then
# install KAINE (editable) with the requested extras.
# =========================================================================
FROM ${BUILD_BASE} AS build
ARG FLAVOR
ARG KAINE_EXTRAS

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build toolchain — CUDA/HIP extensions may compile during pip; git lets pip
# resolve any VCS deps; ca-certificates/gnupg back the deadsnakes PPA fetch below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates gnupg \
 && rm -rf /var/lib/apt/lists/*

# python3.12 + venv + dev headers. Already present on python:3.12-slim (the CPU
# build base) — the guard is a no-op there. On the CUDA build base (Ubuntu jammy,
# whose apt ships only python3.10) it comes from the deadsnakes PPA.
RUN if ! command -v python3.12 >/dev/null 2>&1; then \
        apt-get update \
     && apt-get install -y --no-install-recommends \
            software-properties-common ca-certificates gnupg \
     && add-apt-repository -y ppa:deadsnakes/ppa \
     && apt-get update \
     && apt-get install -y --no-install-recommends \
            python3.12 python3.12-venv python3.12-dev \
     && rm -rf /var/lib/apt/lists/*; \
    fi

RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --upgrade pip

# Single source of truth for the wheel index: copy ONLY install.py first so the
# torch layer caches independently of the rest of the source tree.
COPY scripts/install.py /src/scripts/install.py
RUN TORCH_INDEX="$(python /src/scripts/install.py --print-index "${FLAVOR}")" \
 && TORCH_SPEC="$(python /src/scripts/install.py --print-torch-spec)" \
 && if [ -n "${TORCH_INDEX}" ]; then \
        pip install --index-url "${TORCH_INDEX}" "${TORCH_SPEC}"; \
    else \
        pip install "${TORCH_SPEC}"; \
    fi

# Now the rest of the source and the editable install with extras.
COPY pyproject.toml README.md /src/
COPY kaine /src/kaine
COPY config /src/config
COPY scripts /src/scripts
WORKDIR /src
RUN pip install -e "${KAINE_EXTRAS}"

# =========================================================================
# Stage 2 — runtime: slim base, non-root user, venv + source copied in, offline
# model guards, /state + /models as volumes. No model weights in any layer.
# =========================================================================
FROM ${RUNTIME_BASE} AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# tini reaps zombies as PID 1; ca-certificates for TLS trust. Both bases.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tini ca-certificates gnupg \
 && rm -rf /var/lib/apt/lists/*

# python3.12 runtime interpreter — the copied-in venv symlinks to it. Present on
# python:3.12-slim (the CPU runtime base); from deadsnakes on the CUDA runtime
# base (Ubuntu jammy). The guard is a no-op when python3.12 already exists.
RUN if ! command -v python3.12 >/dev/null 2>&1; then \
        apt-get update \
     && apt-get install -y --no-install-recommends \
            software-properties-common ca-certificates gnupg \
     && add-apt-repository -y ppa:deadsnakes/ppa \
     && apt-get update \
     && apt-get install -y --no-install-recommends python3.12 \
     && rm -rf /var/lib/apt/lists/*; \
    fi

# Non-root runtime user (design §7): owns /state and /models; owner-only perms
# are established by the entrypoint on the mounted volumes, never baked in.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin kaine \
 && mkdir -p /state /models /app \
 && chown -R kaine:kaine /state /models /app

COPY --from=build /opt/venv /opt/venv
# Source (editable install target) — NO config/secrets.toml, NO state/, NO
# voices/adapters enter the image; .dockerignore enforces the build-context side.
COPY --chown=kaine:kaine kaine /app/kaine
COPY --chown=kaine:kaine config/kaine.toml /app/config/kaine.toml
COPY --chown=kaine:kaine pyproject.toml README.md /app/
COPY --chown=kaine:kaine scripts /app/scripts
COPY --chown=kaine:kaine docker/entrypoint.sh /usr/local/bin/kaine-entrypoint

WORKDIR /app
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

VOLUME ["/state", "/models"]
USER kaine

# tini reaps zombies; the entrypoint fixes volume perms then dispatches. The
# default CMD is the cognitive cycle — but the cycle STILL refuses to boot
# without KAINE_CYCLE_OPERATOR_PRESENT=1 (or the research safety net), so a bare
# `docker run` of this image never starts an entity. The Nexus service overrides
# CMD with `-m kaine.nexus`.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/kaine-entrypoint"]
CMD ["python", "-m", "kaine.cycle"]
