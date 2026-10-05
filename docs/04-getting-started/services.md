# Supporting services

Before the KAINE cycle starts, bring up the services its default entity relies on. With no profile selected, the loader applies the `thesis_test` profile. The shipped `config/kaine.toml` alone has every module off; `thesis_test` therefore defines the default entity, with the caveat that `config/kaine.operator.toml` merges last and wins. The first-run wizard (`python -m kaine.setup`) always writes a full `[modules]` table there, so after the wizard has run its module choices replace the profile's. `thesis_test` turns on Soma, Chronos, Topos, Audition, Lingua and Thymos and turns everything else off, including Phantasia, Hypnos, Nous, Mnemos, Perception and Mundus. It also sets `[perception_feed]` mode to `"seeded"` with seed `0`, `[topos].foveation = true`, `[audition].transcription_enabled = false` and `general_audition = true`, and `[volition]` policy `"self_initiated_report"`, `drive_initiative = false`, `sig_expiry_s = 300.0`. Every other value comes from the shipped `config/kaine.toml`.

This page is for the operator installing and starting those services. The supervised first boot is covered in [First boot](first-boot.md).

## What the default entity needs

`thesis_test` sets the `[modules]` flags, `[perception_feed]` mode and seed, `[topos].foveation`, `[audition].transcription_enabled` and `general_audition`, and `[volition]` policy, `drive_initiative` and `sig_expiry_s`. Everything else comes from the shipped `config/kaine.toml`. For a default run, start:

- Redis — the cycle's event bus.
- Qdrant — required by `scripts/first-boot.sh` (Mnemos is off in the default profile).
- The model server — the OpenAI-compatible server that hosts the [Lingua](../09-modules/lingua.md) organ.
- Speaches — if you switch [Audition](../09-modules/audition.md) to the `speaches` backend or enable `transcription_enabled`.
- Chatterbox — if you enable [Vox](../09-modules/vox.md) and use the `chatterbox` backend.

You can avoid the separate speech services by switching Audition and Vox to `sherpa_onnx`.

## Redis (event bus)

KAINE runs its own Redis container, isolated from any system Redis.

```bash
bash scripts/redis-bootstrap.sh
```

The script creates a password on first run, writes it to `compose/.env` and `config/secrets.toml` (both are set to `chmod 600`; other entries are left alone), starts the `kaine-redis` container, and confirms `PONG`. Re-running keeps the existing password. Use `--rotate` to replace it; if the container is already running, pass `--container` too, or the script refuses. Anything still connected — Nexus or a running cycle — must be restarted after a rotation.

Check the container:

```bash
docker compose -f compose/redis.yml ps
```

You should see `kaine-redis` healthy.

## Qdrant (vector memory)

```bash
bash scripts/qdrant-bootstrap.sh
```

The script creates an API key on first run, stores it in `compose/.env` and `config/secrets.toml`, and starts the Qdrant container from `qdrant/qdrant:v1.19.1` on `127.0.0.1:6533` (distinct from a system Qdrant on 6333). Re-running keeps the existing key. Use `--rotate` to replace it; if the container is already running, pass `--container` too, or the script refuses.

Verify:

```bash
curl -s http://127.0.0.1:6533/readyz
```

## Running services without Docker

Redis and Qdrant also run as user-level native services, with no container runtime and no root. This is the default on hosts without Docker; force it with `--native`:

```bash
bash scripts/redis-bootstrap.sh --native
bash scripts/qdrant-bootstrap.sh --native
```

By default, native Redis stores its config, AOF and pid file under `state/services/redis/` and listens on `127.0.0.1:6479`. Native Qdrant downloads the pinned v1.19.1 release binary, checks its sha256, and runs from `state/services/qdrant/` on `127.0.0.1:6533`. If you set `[storage].data_root` in config or set `KAINE_DATA_ROOT`, the native service directories move to `<data root>/state/services/<svc>/` instead.

Both services are supervised by `systemd --user` when it is available; otherwise they use a pid file under the service directory.

To install Qdrant on a host without internet, download the release archive elsewhere and point the bootstrap at it:

```bash
KAINE_QDRANT_ARCHIVE=/path/to/qdrant-<arch>.tar.gz bash scripts/qdrant-bootstrap.sh
```

The archive is still checked against the same pinned sha256.

On Termux, `bash scripts/redis-bootstrap.sh --native` uses the `redis` package (`pkg install redis` if it is missing). Qdrant has no Android build; set `[mnemos].backend = "sqlite_vec"` in `config/kaine.operator.toml` and skip Qdrant.

## Service helper

Control native services with:

```bash
scripts/services.sh status
scripts/services.sh start redis
scripts/services.sh stop
```

`stop` with no service name acts on this checkout's native Redis and Qdrant. Containers are shared by every checkout on the host and may hold a running entity's bus and memory, so stopping a container needs the `--container` flag:

```bash
scripts/services.sh stop redis --container
```

That stops the container but does not remove it.

## Model server (language organ)

If [Lingua](../09-modules/lingua.md) is enabled, the model server serves the published KAINE organ. The first-run wizard, `python -m kaine.setup`, can download and start it hardware-aware and with explicit consent. The manual steps are below.

### Download the organ

The wizard runs the right `hf download` command for the host. The served GGUF lands at a deterministic local path under `state/models/...` so the bootstrap can point the server at the real file. By hand:

```bash
# always — the single served GGUF
hf download kaineone/Qwen3.5-4B-abliterated-GGUF KAINE-Qwen3.5-4B-abliterated.Q4_K_M.gguf \
  --local-dir state/models/Qwen3.5-4B-abliterated-GGUF

# only for Stage-2 voice-alignment training — the trainer's base_model_path
hf download kaineone/Qwen3.5-4B-abliterated
```

A serve-only host skips the larger safetensors pull.

### Launch and supervise the server

```bash
bash scripts/model-server-bootstrap.sh start   # locate binary, launch, health-gate
bash scripts/model-server-bootstrap.sh status  # is the configured alias served?
bash scripts/model-server-bootstrap.sh stop
```

The bootstrap never silently installs the multi-GB server toolchain. If the binary is missing, it prints install guidance and exits non-zero.

On NVIDIA it uses Unsloth Studio's `llama-server` (`~/.unsloth/llama.cpp/build/bin/llama-server`); on AMD/ROCm it uses the unsloth-core build. Override the binary with `KAINE_MODEL_SERVER_BIN`.

### Idle unload

The shipped config sets `[lingua].model_server_sleep_idle_seconds = 600`. After 600 seconds with no requests, the server unloads the organ from VRAM. Set it to `-1` to keep the model loaded.

### Organ formats

| Format | Repo | When | Why |
| --- | --- | --- | --- |
| GGUF | `kaineone/Qwen3.5-4B-abliterated-GGUF` | always when Lingua is enabled | served by the OpenAI-compatible model server |
| safetensors | `kaineone/Qwen3.5-4B-abliterated` | only when Stage-2 voice-alignment training is enabled | the trainer's `base_model_path` |

### Served-alias check

The server must list the organ under the exact value of `[lingua].model_id`. The bootstrap launches with `--alias` set to that value. The wizard checks this after launch and reports a clear "served name ≠ configured name" message, so the first cycle does not hit a 404.

Chain-of-thought is suppressed at the server with `--reasoning-budget 0` and in requests with `chat_template_kwargs = {"enable_thinking": false}`. Lingua is a voice, not a reasoner.

Verify the alias is served:

```bash
curl -s http://127.0.0.1:11434/v1/models | python3 -m json.tool
```

A keyed organ (the containerized one when `KAINE_MODEL_SERVER_API_KEY` is set) answers 401 without the key, so send it as a bearer header:

```bash
curl -s -H "Authorization: Bearer $KAINE_MODEL_SERVER_API_KEY" http://127.0.0.1:11434/v1/models | python3 -m json.tool
```

### Mute-organ gate

The cycle refuses to boot if the organ returns no content. Set `KAINE_ALLOW_MUTE_ORGAN=1` to override that gate.

## Speech services

The default entity has [Audition](../09-modules/audition.md) enabled with `transcription_enabled = false`, so STT is bypassed. The health board lists Speaches as `not configured` when transcription is disabled; that is expected. Speaches is only needed if you switch Audition to the `speaches` backend or set `transcription_enabled = true`. [Vox](../09-modules/vox.md) is off by default; enable it only if you want TTS.

### Speaches STT

If Audition uses the `speaches` backend, run Speaches on CPU with the `medium.en` model. Use the upstream Speaches project, or the `kaine-speaches` Quadlet unit if you installed the units in `quadlet/` ([quadlet/README.md](../../quadlet/README.md)):

```bash
systemctl --user restart kaine-speaches.service   # Quadlet install only
curl -fsS http://127.0.0.1:8000/v1/models
```

A cuDNN crash or a 404 at this endpoint breaks the voice loop. See [Troubleshooting](../06-operation/troubleshooting.md).

### Chatterbox TTS

If Vox uses the `chatterbox` backend, run Chatterbox. Use the upstream project, or the `kaine-chatterbox` Quadlet unit:

```bash
systemctl --user restart kaine-chatterbox.service   # Quadlet install only
curl -s http://127.0.0.1:8883/
```

Chatterbox needs a predefined voice id. Set `[vox].predefined_voice_id` in `config/kaine.operator.toml` to a filename Chatterbox can find under its `voices/` directory before you enable Vox.

### sherpa-onnx

To run STT and TTS inside KAINE instead of using Speaches and Chatterbox, set:

```toml
[audition]
backend = "sherpa_onnx"

[vox]
backend = "sherpa_onnx"
```

Then download the models:

```bash
python -m kaine.setup.speech_models
```

This is the path used by the edge portability profiles.

## Voice-alignment trainer

Stage-2 voice-alignment training needs a separate trainer environment. Configure it in `[hypnos.voice_alignment]` in `config/kaine.operator.toml`:

- `trainer_backend = "subprocess"` runs the trainer in a local Python environment; set `trainer_python` to its interpreter.
- `trainer_backend = "job_queue"` plus the `kaine-trainer` compose service is for container hosts.
- `hot_swap_mode = "organ_adapter"` lets the trainer hot-swap the organ adapter.

See [Voice alignment](../10-sleep/voice-alignment.md) for the full setup.
