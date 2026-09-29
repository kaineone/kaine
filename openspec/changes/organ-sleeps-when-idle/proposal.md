## Why

The operator wants the organ unloaded whenever KAINE is not running: "that should always be unloaded when kaine is shutdown anyway."

Today the organ, the llama.cpp server behind `[lingua].chat_url`, is an always-on service (`kaine-model-server`, `restart: unless-stopped`). It holds about 10 GB of GPU memory whether or not any cycle or study is running. Freeing the GPU for other work means stopping the container by hand.

Two earlier designs touch this:
- **The Hypnos organ window** stops and starts the organ natively (`kaine.setup.model_server`). A containerized cycle cannot do that without the Docker socket, which it must never have.
- **`module-residency-and-speech-tiers`** delegates LLM residency to a proxy with an idle timeout. That brings in a third-party binary and a larger change.

The organ's own server already has what is needed. llama.cpp's `llama-server` has a first-party `--sleep-idle-seconds` option (build 9976, the image in use). After that many idle seconds, it unloads the model and its KV cache. The next inference request reloads it.

A check on this host (CPU, 20 s sleep, 2026-09-29) confirmed the behaviour KAINE relies on:
- Polling `/v1/models` every 5 s, as Nexus's health probe and the GPU preflight do, neither prevents sleep nor wakes the model, and it keeps answering 200.
- `/props` reports `is_sleeping`.
- A real completion wakes the model in about 1.5 s.

## What Changes

- **The organ sleeps when idle.**
  - Every organ launch path passes `--sleep-idle-seconds`: the compose default command, the Quadlet unit and the native launcher (`kaine.setup.model_server.build_launch_cmd`).
  - The value comes from `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` in compose and Quadlet, and from `[lingua].model_server_sleep_idle_seconds` natively. The default is 600.
  - So the organ unloads within ten minutes of the last cycle or study stopping, and reloads on the next request with no operator action.
  - An operator who overrides `KAINE_MODEL_SERVER_CMD` passes the flag themselves; the docs say so.
- **Health shows sleep as a normal state.**
  - Nexus's organ probe and the pre-boot `Chat LLM` row read `/props` and report the organ as up and asleep, not as degraded.
  - The pre-boot `Organ content` row still sends a real completion, which wakes the organ, so a boot always proves the organ answers.
- **Verification at the next launch.** On the GPU, confirm that sleeping releases the organ's VRAM, as `nvidia-smi` shows.
  - Upstream issue ggml-org/llama.cpp#19379 reports that ROUTER mode keeps a subprocess on the GPU after sleep. KAINE runs single-model mode.
  - If VRAM is not released, the change stops at documenting that, and the residency proxy path remains the answer.
- **Unchanged.**
  - The organ's model and API are unchanged, and there is no new dependency or network exposure.
  - The Hypnos organ window keeps working, since a stopped server and a sleeping one reload the same way.

## Capabilities

### Modified Capabilities
- `inference-backend`: the organ unloads when idle and reloads on demand, and health distinguishes asleep from down.

## Impact

- **Code and config:**
  - `compose/kaine.yml`;
  - `quadlet/kaine-model-server.container`;
  - `kaine/setup/model_server.py`;
  - `kaine/nexus/health/probes.py`;
  - `kaine/preboot.py`;
  - `config/kaine.toml`;
  - `compose/.env.example`;
  - docs.
- **Latency:** the first request after a sleep takes about a second or two longer while the model reloads.
