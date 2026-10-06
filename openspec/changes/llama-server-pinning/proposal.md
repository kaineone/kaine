# Pin the model server and make its settings explicit

## Why
- **The committed defaults float.** The organ image defaults to `ghcr.io/ggml-org/llama.cpp:server-cuda`, `:server-rocm` and `:server` in compose and quadlet. Only this host pins a build, and only in its gitignored `compose/.env`. Any other install, or this one after a `docker pull`, can run a different server build from the one a study was calibrated on.
- **The trainer's converter is on an older build.** It converts adapters with llama.cpp b9976, while the organ serves b11382. An adapter is converted by one build and loaded by another.
- **Memory and determinism settings are implicit.** The server picks its GPU layers from whatever memory is free at launch (`--fit` is on by default). It reserves 8 GiB of host RAM for the prompt cache (`--cache-ram`). Nothing states the KV-cache type, although a quantized K cache makes identical prefix-cache repeats differ (llama.cpp #28527). So the same configuration can load differently on different days.

The AI-alternatives report (2026-10-05, §6.2 item 6) lists these, and the operator approved the work as D4.

## What changes
- **Image pins.** The compose CUDA, ROCm and CPU files and the quadlet unit default to build b11382 by digest:
  - CUDA `sha256:ef08b5a9…`
  - ROCm `sha256:46583bd1…`
  - CPU `sha256:559ac229…`

  `KAINE_MODEL_SERVER_IMAGE` still overrides. The `.env` example and the deployment docs say to pin by digest.
- **One build everywhere.** The trainer's converter moves to b11382, with the tarball's SHA-256 checked. A test keeps the converter build and the organ pins on the same build.
- **Explicit settings on every organ command line:**
  - `--fit off` with `-ngl ${KAINE_MODEL_SERVER_NGL:-999}`: every layer on the GPU, or the load fails loudly, never a silent partial offload;
  - `--cache-ram ${KAINE_MODEL_SERVER_CACHE_RAM_MIB:-1024}`;
  - `-ctk f16 -ctv f16`.
- **No slot saving.** Slot saving (`--slot-save-path`) is never enabled. It would write sensory-derived KV cache to disk, and a test forbids it.

## Impact
- Specs: `inference-backend`.
- Code: `compose/kaine.yml`, `compose/kaine.cpu.yml`, `compose/kaine.rocm.yml`, `compose/.env.example`, `quadlet/kaine-model-server.container`, `Dockerfile`, `docs/07-deployment/containers.md`, tests.
- **Research impact: none for outputs, but this is a reproducibility fix.** This host already runs b11382. On this GPU, full offload is what `--fit` chose anyway, and f16 is the default KV type. The settings become explicit and pinned, so a later run can't drift. The converter change affects only voice-alignment adapter conversion, which is off until voice development is validated.
