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
# Extras installed into the image. [full] carries every runtime extra (the base
# install no longer includes torch or the memory stack); pass a leaner set to
# build a smaller image. The abliterated organ, STT/TTS models, and embedders are
# provisioned to the volume, not here.
ARG KAINE_EXTRAS=".[test,full]"

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

# Single source of truth for the wheel index: copy install.py and pyproject.toml
# first so the torch layer caches independently of the rest of the source tree.
# The torch layer also re-builds when pyproject.toml changes, which is required
# so the image follows the project torch requirement.
COPY scripts/install.py /src/scripts/install.py
COPY pyproject.toml /src/pyproject.toml
RUN TORCH_INDEX="$(python /src/scripts/install.py --print-index "${FLAVOR}")" \
 && TORCH_SPEC="$(python /src/scripts/install.py --print-torch-spec)" \
 && if [ -n "${TORCH_INDEX}" ]; then \
        pip install --index-url "${TORCH_INDEX}" "${TORCH_SPEC}" torchvision; \
    else \
        pip install "${TORCH_SPEC}" torchvision; \
    fi \
 && python -c "import importlib.metadata as md; names=('torch','torchvision','torchaudio'); installed={d.metadata.get('Name','').lower():d.version for d in md.distributions()}; open('/src/kaine-torch-constraints.txt','w').write(''.join(f'{n}=={installed[n]}\n' for n in names if n in installed))"

# Now the rest of the source and the editable install with extras.
# The editable install records where the package lives, so it is made from
# /app — the same path the runtime stage copies the source to. Installing from
# anywhere else leaves the runtime venv pointing at a directory the image does
# not contain, and `kaine` then imports only when the working directory is /app.
COPY pyproject.toml README.md /app/
COPY kaine /app/kaine
COPY config /app/config
COPY scripts /app/scripts
WORKDIR /app
# PIP_ONLY_BINARY=av forces the prebuilt PyAV wheel (bundles ffmpeg) when the
# [audio] extra is selected. Its source tarball needs pkg-config + ffmpeg-dev and
# would leave a runtime .so dependency the slim runtime stage lacks — the wheel is
# self-contained. No effect on builds that don't pull av (the lean default).
# Pass the torch-stack constraints file so the extras cannot re-resolve torch.
RUN PIP_ONLY_BINARY=av pip install -c /src/kaine-torch-constraints.txt -e "${KAINE_EXTRAS}"

# =========================================================================
# Stage 2 — runtime: slim base, non-root user, venv + source copied in, offline
# model guards, /app/state + /models as volumes. No model weights in any layer.
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

# Non-root runtime user (design §7): owns /app/state and /models; owner-only perms
# are established by the entrypoint on the mounted volumes, never baked in. The
# entity state volume mounts at /app/state (the app writes state CWD-relative
# under WORKDIR /app, below), so that dir must exist kaine-owned in the image for
# a freshly created named volume to inherit owner-only perms. /app/studies is
# the module-ignition study volume's mountpoint, kaine-owned for the same reason.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin kaine \
 && mkdir -p /app/state /app/studies /models /organ-adapters /trainer-jobs /app/state/hypnos/voice_align_jobs \
 && chown -R kaine:kaine /app /models /organ-adapters /trainer-jobs

COPY --from=build /opt/venv /opt/venv
# Source (editable install target) — NO config/secrets.toml, NO state/, NO
# voices/adapters enter the image; .dockerignore enforces the build-context side.
COPY --chown=kaine:kaine kaine /app/kaine
# Vendored, revision-pinned InternVideo-Next modeling source (the shipped default
# vision backend loads it from /app/external/internvideo_next with
# trust_remote_code=False). Committed Python + config only — the .safetensors
# weights are excluded by .dockerignore and provisioned to the model volume, not
# baked in. Without this the default encoder cannot load in the container.
COPY --chown=kaine:kaine external/internvideo_next /app/external/internvideo_next
ARG GIT_SHA=""
COPY --chown=kaine:kaine config/kaine.toml /app/config/kaine.toml
# Runtime profiles (incl. thesis_test auto-selection) must be in-image or
# KAINE_PROFILE resolution fails inside the container.
COPY --chown=kaine:kaine config/profiles /app/config/profiles
COPY --chown=kaine:kaine pyproject.toml README.md /app/
COPY --chown=kaine:kaine scripts /app/scripts
# Abliteration probe set: shipped read-only in the image so the boot-time
# voice-alignment veto can find it; no entity state or private data is included.
COPY --chown=kaine:kaine eval_probes /app/eval_probes
COPY --chown=kaine:kaine docker/entrypoint.sh /usr/local/bin/kaine-entrypoint

WORKDIR /app
ENV KAINE_GIT_SHA=${GIT_SHA} \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

VOLUME ["/app/state", "/models"]
USER kaine

# tini reaps zombies; the entrypoint fixes volume perms then dispatches. The
# default CMD is the cognitive cycle — but the cycle STILL refuses to boot
# without KAINE_CYCLE_OPERATOR_PRESENT=1 (or the research safety net), so a bare
# `docker run` of this image never starts an entity. The Nexus service overrides
# CMD with `-m kaine.nexus`.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/kaine-entrypoint"]
CMD ["python", "-m", "kaine.cycle"]

# =========================================================================
# Stage 3 — trainer-build: an isolated venv for the [training] extra and the
# llama.cpp LoRA -> GGUF converter used by kaine-trainer.
#
# The trainer image is built only with --target trainer; the default target is
# the runtime image (see the runtime-default alias at the end of this file).
# =========================================================================
FROM build AS trainer-build
ARG FLAVOR
ARG LLAMA_CPP_TAG=b9976
ARG LLAMA_CPP_SHA256=d54ff9d66fb07b8c295f1d0fd01ce267392409d05cc5c5c89bf83d7d4debd130

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is needed to fetch the pinned llama.cpp source archive; the build base
# may not ship it (e.g. the CUDA devel image does not).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Separate venv so the [training] stack never touches the runtime venv.
RUN python3.12 -m venv /opt/trainer
ENV PATH="/opt/trainer/bin:${PATH}"

# The trainer venv carries its own torch because the training stack (unsloth)
# supports an older torch than the runtime. The runtime torch is unaffected.
RUN TORCH_INDEX="$(python /src/scripts/install.py --print-index "${FLAVOR}")" \
 && if [ -n "${TORCH_INDEX}" ]; then \
        /opt/trainer/bin/pip install --index-url "${TORCH_INDEX}" "torch>=2.10,<2.13" torchvision; \
    else \
        /opt/trainer/bin/pip install "torch>=2.10,<2.13" torchvision; \
    fi \
 && /opt/trainer/bin/python -c "import importlib.metadata as md; names=('torch','torchvision','torchaudio'); installed={d.metadata.get('Name','').lower():d.version for d in md.distributions()}; open('/src/trainer-torch-constraints.txt','w').write(''.join(f'{n}=={installed[n]}\n' for n in names if n in installed))"

# Install only the [training] extra's dependencies, WITHOUT installing kaine
# itself (the trainer service code lives in the runtime image /app/kaine).
RUN python3.12 -c "import pathlib, tomllib; print('\n'.join(tomllib.loads(pathlib.Path('/src/pyproject.toml').read_text(encoding='utf-8'))['project']['optional-dependencies']['training']))" > /tmp/training-reqs.txt && /opt/trainer/bin/pip install -c /src/trainer-torch-constraints.txt -r /tmp/training-reqs.txt

# Fetch the pinned llama.cpp tag used by the organ image and verify it.
# Extract the explicit files/packages convert_lora_to_gguf needs: the two
# converters, the conversion package, and gguf-py.
RUN curl -fsSL -o /tmp/llama.tgz "https://github.com/ggml-org/llama.cpp/archive/refs/tags/${LLAMA_CPP_TAG}.tar.gz" \
 && echo "${LLAMA_CPP_SHA256}  /tmp/llama.tgz" | sha256sum -c - \
 && mkdir -p /opt/llama.cpp \
 && tar -xzf /tmp/llama.tgz -C /opt/llama.cpp --strip-components=1 "llama.cpp-${LLAMA_CPP_TAG}/convert_lora_to_gguf.py" "llama.cpp-${LLAMA_CPP_TAG}/convert_hf_to_gguf.py" "llama.cpp-${LLAMA_CPP_TAG}/conversion" "llama.cpp-${LLAMA_CPP_TAG}/gguf-py" \
 && rm /tmp/llama.tgz

# Install the gguf-py package into the trainer venv, plus sentencepiece/protobuf
# which convert_lora_to_gguf needs but which the llama.cpp requirements files
# would otherwise pin to a different torch.
RUN /opt/trainer/bin/pip install /opt/llama.cpp/gguf-py sentencepiece protobuf

# =========================================================================
# Stage 4 — trainer: runtime image + the isolated trainer venv + converter.
# =========================================================================
FROM runtime AS trainer

COPY --chown=kaine:kaine --from=trainer-build /opt/trainer /opt/trainer
COPY --chown=kaine:kaine --from=trainer-build /opt/llama.cpp /opt/llama.cpp

ENV KAINE_TRAINER_PYTHON=/opt/trainer/bin/python \
    KAINE_LORA_CONVERTER=/opt/llama.cpp/convert_lora_to_gguf.py

USER kaine

# The runtime venv's `python` runs the trainer service; the trainer venv is used
# only for the subprocess training/conversion calls it spawns.
CMD ["python", "-m", "kaine.modules.hypnos.trainer_service"]

# =========================================================================
# Default target: the runtime image. The trainer stage above derives from the
# runtime stage, so this alias keeps `docker build .` producing the runtime.
# =========================================================================
FROM runtime AS runtime-default
