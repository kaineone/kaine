# Getting started

This page is for operators installing KAINE for the first time. It covers the one-command bootstrap, host requirements, the install script, the browser first-run wizard, and the optional extras that enable specific modules. After the install finishes, continue with [Supporting services](services.md) and [First boot](first-boot.md) to bring up the runtime and start the entity.

## One command on any host

Clone and prepare the host with a single shell command. The script installs system packages if you consent, installs KAINE, runs the Redis and Qdrant bootstrap scripts unconditionally, and starts the first-run wizard directly when stdin is a TTY. It never boots the entity.

```bash
bash <(curl -fsSL https://your-repo.example/kaine/scripts/bootstrap.sh) --repo https://your-repo.example/kaine.git --yes
```

Replace the URLs with your own fork of the repository.

| Target | Detected by | Flavor | Extras | What runs |
|---|---|---|---|---|
| Desktop NVIDIA | working `nvidia-smi -L` | `cuda` | `full` | all modules |
| Desktop AMD | `rocm-smi` on PATH or `/opt/rocm` | `rocm` | `full` | all modules |
| Desktop Intel | `xpu-smi` or `sycl-ls` | `xpu` | `full` | all modules |
| Desktop CPU | x86_64 Linux, no accelerator | `cpu` | `full` | all modules |
| Jetson / Tegra | `/etc/nv_tegra_release` or device-tree Tegra markers | `cuda` | `full,speech-edge` | all modules; aarch64 cu13x wheel |
| Generic aarch64 CPU | aarch64 Linux, not Tegra | `cpu` | `full,speech-edge` | all modules |
| macOS | Darwin | `mps` on Apple Silicon, `cpu` otherwise | `full` | all modules |
| Termux / Android | `TERMUX_VERSION` or `com.termux` prefix | `cpu` | `memory-edge` | edge memory modules; `speech-edge` is a manual install; Topos is excluded |

The bootstrap script prints the system-package command for your package manager (`apt`, `dnf`, `pacman`, `pkg`, or `brew`) and only runs it when you pass `--yes`. It does not start the entity and does not assume root: `sudo` commands prompt the operator.

## Browser first-run wizard

Open the loopback setup wizard in a browser with:

```bash
.venv/bin/python -m kaine.setup --web
```

The server binds to `127.0.0.1` on a free port, prints a single-use launch URL to the terminal, and opens a private redirect file in the default browser. The URL with the launch token never appears in a browser command line.

Both the browser and the terminal wizard write your choices to a gitignored `config/kaine.operator.toml`. `load_kaine_config()` deep-merges that file over the shipped `config/kaine.toml` at boot, so operator values win and the committed file stays untouched. Neither wizard edits the shipped config or boots the entity.

The wizard walks through the same steps as the terminal version:

1. A short orientation.
2. CAL welfare acknowledgement — a summary of the Article 4 care obligations and a required typed acknowledgement before any entity is configured.
3. Hardware — lists every compute device, allowed-device selection, the proposed device map (`[hardware.devices]`: `organ` and `vision`), CPU threads, shared services (`[services.<name>].shared`), and data-root selection. It also recommends a deployment tier and warns about accelerator mismatches.
4. Module selection — the wizard offers two presets or a custom set. The **base thesis** is the module set of `config/profiles/thesis_test.toml` (Soma, Chronos, Thymos, Lingua, Topos and Audition). The **full entity** turns on all fourteen cognitive modules; the embodiment modules, Perception and Mundus, stay off. The wizard recommends the full entity when the hardware step found a tier of 2 or higher that runs every module at once without swapping modules in and out, and the base thesis otherwise, including when it has no tier recommendation. **Custom** asks about each module, starting from the recommended preset. `--defaults` takes the recommendation. The wizard writes a full `[modules]` table to `config/kaine.operator.toml`, which merges last and wins, so after the wizard has run its choices replace the `thesis_test` profile's.
5. Model, voice, and STT — discovers served options from the model server, Chatterbox, and Speaches when reachable, otherwise accepts manual entry, and records `[lingua].model_id`, `[vox].predefined_voice_id`, and `[audition].stt_model`. If you enable Hypnos voice alignment, it also provisions the Stage-2 trainer (`[hypnos.voice_alignment].trainer_backend`).
6. Optional CL1 integration — an opt-in connection to a CL1 instance if configured. See [Plugins and CL1](../19-plugins-and-cl1.md).
7. Consented organ download and serve — downloads and serves the selected organ model only if you consent.
8. Research metrics — an opt-in, metrics-only research submission (off by default).
9. State encryption — the shipped `config/kaine.toml` already has `[security.state_encryption].enabled = true`. The wizard asks "Enable state encryption at rest?" with a default of No; declining writes nothing, so the shipped value stays in force. If encryption is enabled, a missing or wrong key refuses boot.
10. Optional extras — offers to `pip install -e ".[…]"` the extras implied by your module choices. This step runs after the operator file is written.
11. External dependencies — detects which services the enabled modules need and whether each is already running. For Redis and Qdrant it shows the exact bootstrap command and runs it only if you consent. For the heavy GPU services (model server, Speaches, Chatterbox) it prints the real setup steps and a docs link rather than pretending to install them.

Saving the operator file creates the Nexus sign-in token in `config/secrets.toml` only if no token exists and the `KAINE_NEXUS_TOKEN` environment variable is unset. The token is only needed when `[nexus].access` is set to `"token"`. The browser wizard then moves to the **jobs** page. Run each consented job there; its output streams live in the page. When the jobs are done, go to the **finish** page.

The finish page shows a service status light for each known local service and for Nexus, a **Start Nexus** button when Nexus is not running, a **Show sign-in token** button, and a **Close setup** button. The sign-in token is read from `config/secrets.toml` or from the `KAINE_NEXUS_TOKEN` environment variable and is shown only when you press the button. The token is never stored in the browser URL or in the session.

## Terminal first-run wizard

Run the same wizard in the terminal with:

```bash
.venv/bin/python -m kaine.setup
```

This is useful when a browser is not available or when you prefer a text interface. Pass `--defaults` to accept safe non-interactive defaults. The terminal wizard writes the same `config/kaine.operator.toml`, creates the same Nexus sign-in token, and ends with a summary of the environment gates, the service bring-up commands and how to launch.

## Prerequisites

### Host software

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 recommended (3.11+ required) | Matches the runtime deps |
| `git` | any recent | — |

Service-specific requirements for Redis, Qdrant, the model server, Speaches, and Chatterbox are in [Supporting services](services.md).

### Supporting services

Every runtime service is local. Model weights download from public repositories during setup; once cached, the system can run without a network connection, though it is not restricted to offline operation.

| Service | Role | Default endpoint |
|---|---|---|
| Redis (container or native) | Event bus (Redis Streams) | `127.0.0.1:6479` |
| Qdrant (container or native) | Memory + social vectors (Mnemos, Empatheia) | `127.0.0.1:6533` |
| Model server | Language organ inference for Lingua — OpenAI-compatible `/v1` | `127.0.0.1:11434` |
| Speaches | STT for Audition (`medium.en`) | `127.0.0.1:8000` |
| Chatterbox TTS | Voice synthesis for Vox | `127.0.0.1:8883` |

If no profile is selected, the loader applies the `thesis_test` profile automatically. That profile turns Soma, Chronos, Topos, Audition, Lingua, and Thymos on and disables every other module. It also sets `[perception_feed]` to `seeded` with seed 0, `[topos].foveation = true`, `[audition].transcription_enabled = false` with `general_audition = true`, and `[volition] policy="self_initiated_report"`, `drive_initiative=false`, `sig_expiry_s=300.0`. Every other value comes from the shipped `config/kaine.toml`.

`config/kaine.operator.toml` merges last and wins, and the first-run wizard always writes a full `[modules]` table there, so after the wizard has run its module choices replace the profile's.

The bootstrap script already starts Redis and Qdrant, and the first-run wizard checks that both answer before the entity can boot. Bring both up even when the enabled modules do not use Qdrant. The model server is needed for Lingua. Speaches is needed only when Audition transcription is enabled; Chatterbox is needed only when Vox is enabled. You can also use the on-device `sherpa_onnx` backend for STT and TTS instead (see [On-device speech](#on-device-speech)).

The model server unloads the Lingua organ after 600 seconds of idle time by default (`[lingua].model_server_sleep_idle_seconds`), freeing VRAM. Set it to `-1` to keep the organ loaded.

> **Speaches must run on CPU with `medium.en`.** Running it on GPU with cuDNN causes crashes, and running it without a loaded model returns HTTP 404 that breaks the voice loop. See [Troubleshooting](../06-operation/troubleshooting.md).

### Optional GPU

KAINE runs on CPU-only hosts. With two GPUs it uses a primary/secondary split:

| Device | Role |
|---|---|
| `cuda:0` (primary GPU) | Lingua inference via the model server; Hypnos voice-alignment training |
| `cuda:1` (secondary GPU) | Topos InternVideo-Next vision encoder; Chatterbox TTS |
| CPU | Chronos CfC, Mnemos embedder, Audition emotion2vec+, Speaches STT, control paths |

VRAM needs depend on the model and batch size. As a planning hint, the shipped config comments describe a served organ at about 3 GB and a 4B LoRA training step at about 9.8 GB; those two do not fit on a single 12 GB device at once, so training time-shares the GPU. See [Hardware](../03-hardware/README.md) for sizing guidance.

Device selection is centralized in `kaine.hardware` and configured per-module via the `device` key in `config/kaine.toml`. `KAINE_FORCE_DEVICE=<device>` overrides every module at once. Unavailable devices fall back safely with a logged warning. When `[hardware].allowed_devices` is set, the resolver normally restricts modules to that set; `KAINE_FORCE_DEVICE` overrides it with a warning, and `cpu` is always allowed.

## Install KAINE

### Clone and run the install script

```bash
git clone <repo-url> kaine
cd kaine
bash scripts/install.sh
```

The script:

1. Detects the host target with `kaine/install_target.py`.
2. Selects a PyTorch wheel index with `kaine/wheel_index.py`. NVIDIA hosts get the matching CUDA index (cu126 through cu132); if no matching CUDA version is found, the installer falls back to the CPU index with a warning. CPU hosts get the CPU index.
3. Creates `.venv/` if it is absent.
4. Installs PyTorch from the chosen index when needed.
5. Runs `pip install -e ".[test,<extras>]"` for the chosen extras (default: `full`).

The script is idempotent, so re-run it safely when `pyproject.toml` changes. When run interactively it offers to launch the first-run wizard; pass `--no-wizard` to skip the prompt.

Force a specific flavor if needed:

```bash
bash scripts/install.sh --cpu
bash scripts/install.sh --cuda
bash scripts/install.sh --rocm
bash scripts/install.sh --xpu
bash scripts/install.sh --mps     # auto on macOS arm64
bash scripts/install.sh --python /path/to/python3.12
```

### Install extras

`bash scripts/install.sh` installs the `full` extra by default. Install only the extras your modules need:

| Extra | Unlocks |
|---|---|
| `core` | Topos; Soma and Chronos with `cfc_backend = "torch"` — `torch`, `ncps` |
| `memory` | Mnemos, Empatheia, Hypnos — `qdrant-client`, `sentence-transformers` |
| `memory-edge` | Mnemos `backend = "sqlite_vec"` — `sqlite-vec` |
| `nexus` | `python -m kaine.nexus` — `fastapi`, `uvicorn`, `jinja2` |
| `nvidia` | Soma GPU telemetry — `pynvml` |
| `vision` | Topos capture/playlist — `opencv-python-headless`, `transformers`, `Pillow` |
| `audio` | Audition capture/playlist — `sounddevice`, `webrtcvad`, `funasr`, `librosa`, `av` |
| `speech-edge` | On-device STT/TTS via sherpa-onnx (`kaine/setup/speech_models.py`) |
| `reasoning` | Nous real engine — `inferactively-pymdp`, `jax[cpu]` |
| `worldmodel` | Phantasia DreamerV3 — `jax[cpu]`, `chex`, `einops` |
| `oscillator` | Syneidesis oscillatory layer — `snntorch`, `scipy` |
| `full` | `core, memory, memory-edge, nexus, nvidia, vision, audio, reasoning, worldmodel, oscillator, internvideo` (desktop default; does not include `speech-edge`, `training`, or `internvideo-flash`) |
| `training` | Voice-alignment DPO stack — opt-in, never in `full` |
| `internvideo` | InternVideo-Next vendored code for Topos — included in `full` |
| `internvideo-flash` | Flash-attention fast path — opt-in GPU-only layer |

Examples:

```bash
bash scripts/install.sh --extras core,memory        # CPU entity, no Nexus/vision
bash scripts/install.sh --extras nexus              # lean operator console only
bash scripts/install.sh --extras full               # desktop default
bash scripts/install.sh --research                  # base install + .[perception]
```

### Dynamic device selection

After installation, verify what KAINE resolved:

```bash
.venv/bin/python -c "from kaine.hardware import describe_host; import json; print(json.dumps(describe_host(), indent=2))"
```

The `cuda_devices` field lists each GPU with name, total VRAM, and free VRAM. The `device` field is the highest-priority base device KAINE detected.

`kaine.hardware.resolve_device` is used by every module that picks a compute device. It reads the `device` key from each module's TOML section and falls back to `cuda:0` (or `cpu` on a CPU host) with a logged warning if the requested device is absent. `KAINE_FORCE_DEVICE` overrides it. When `[hardware].allowed_devices` is set, the resolver normally restricts modules to that set; `KAINE_FORCE_DEVICE` overrides it with a warning, and `cpu` is always allowed.

### GPU and accelerator support

| Backend | Device string | Install command | Status |
|---|---|---|---|
| NVIDIA CUDA | `cuda` / `cuda:N` | `bash scripts/install.sh --cuda` (auto-detected) | Supported — primary target |
| AMD ROCm | `cuda` / `cuda:N` (ROCm reports as `cuda`; distinguished by HIP build) | `bash scripts/install.sh --rocm` | Supported — best-effort |
| Intel Arc / XPU | `xpu` / `xpu:N` | `bash scripts/install.sh --xpu` | Supported — best-effort |
| Apple Silicon (MPS) | `mps` | `bash scripts/install.sh --mps` (auto on macOS arm64) | Supported — best-effort |
| CPU only | `cpu` | `bash scripts/install.sh --cpu` (auto-detected) | Supported — always available |

NVIDIA CUDA is the primary tested configuration. AMD ROCm, Intel Arc/XPU, and Apple MPS receive community testing. CPU-only always works.

See [Accelerators and PyTorch wheels](../03-hardware/accelerators.md) for detailed wheel selection.

Nexus ships with `[nexus].access = "open"` by default: viewing and control are open with no token or sign-in. Set it to `"token"` or export `KAINE_NEXUS_ACCESS=token` to require the operator token and session sign-in. `KAINE_NEXUS_READ_ONLY=1` refuses every request except GET/HEAD/OPTIONS with 403. `KAINE_NEXUS_EXTRA_HOSTS` adds tailnet hostnames. Host and Origin checks always apply.

For container hosts, see [Containers](../07-deployment/containers.md).

## Optional extras

### Live perception

Required when `[audition].capture_enabled = true` or `[topos].capture_enabled = true`:

```bash
.venv/bin/pip install -e ".[audio,vision]"
```

Use `.venv/bin/pip`, not the system pip. The `pep668` banner you see in a bare shell is the distribution protecting its Python; the venv pip sidesteps it cleanly.

The `[audio]` extra includes `sounddevice`, `webrtcvad`, `funasr` (pulls `torchaudio`), `librosa`, and `av` (PyAV — decodes the playlist audio track for the reproducible perception feed's `PlaylistAudioStream`).

The `[vision]` extra includes `opencv-python-headless`, `transformers`, and `Pillow`.

System packages that may be needed once:

```bash
sudo apt install libportaudio2        # only if sounddevice raises OSError: PortAudio library not found
sudo apt install build-essential python3-dev  # only if webrtcvad tries to compile from source
```

Smoke test after install:

```bash
.venv/bin/python -c "import sounddevice, webrtcvad, cv2; print('ok')"
```

### On-device speech

As an alternative to Speaches and Chatterbox, set both backends to `sherpa_onnx`:

```toml
[audition]
backend = "sherpa_onnx"

[vox]
backend = "sherpa_onnx"
```

Install the `speech-edge` extra and pull the models:

```bash
bash scripts/install.sh --extras speech-edge
.venv/bin/python -m kaine.setup.speech_models
```

### Research perception feed

With no profile selected, the loader applies the `thesis_test` profile, which sets `[perception_feed].mode = "seeded"`; the shipped `config/kaine.toml` has `mode = "off"`. `seeded` needs no media: it is a pure-NumPy procedural generator, reproducible per seed but not research-grade. The live upgrade is a fixed reference stimulus corpus: `[perception_feed].mode = "playlist"` decodes real, openly-licensed video-with-audio for both senses — OpenCV for the video track and PyAV for the audio track — pinned by a per-item sha256 manifest built with `tools/build_playlist_manifest.py`. Set the manifest path in `config/kaine.operator.toml`, never the shipped profile. See [Configuration — perception and sleep](../appendix-a-configuration/perception-and-sleep.md).

Install both surfaces in one name:

```bash
bash scripts/install.sh --research
# or, into an existing venv:
.venv/bin/pip install -e ".[perception]"
```

`seeded` mode needs neither extra. Without PyAV, a `playlist` audio source raises `PerceptionUnavailableError` with an install hint.

### Active inference

Required when `[modules].nous = true`:

```bash
.venv/bin/pip install -e ".[reasoning]"
```

Installs `inferactively-pymdp>=1.0` and `jax[cpu]`. JAX runs CPU-only at runtime by design. JAX logs a one-line GPU-fallback notice on import — this is expected behavior.

### Oscillatory binding layer

Required when `[oscillator].enabled = true`:

```bash
.venv/bin/pip install -e ".[oscillator]"
```

Installs `snntorch>=0.9` and `scipy`. Without this extra, modules report a neutral phase and the coherence factor degrades to 1.0 (the oscillatory layer is a no-op, not an error).

### World model

Required when `[phantasia].backend = "dreamerv3"`:

```bash
.venv/bin/pip install -e ".[worldmodel]"
```

Installs `jax[cpu]`, `chex`, and `einops`. The shipped default is `backend = "dreamerv3"` with `engine = "jax"`, and `training_enabled` and `persist_weights` both default to true. Use `backend = "fake"` to run with no extra dependencies.

### Voice alignment training

Required when `[hypnos.voice_alignment].enabled = true` and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` is set:

```bash
.venv/bin/pip install -e ".[training]"
```

Installs `unsloth`, `trl`, `peft`, and `datasets` (~3-4 GB). Without this extra the sleep cycle's voice-alignment phase logs a clean "extras not installed" message and continues; no other sleep phase is affected.

`[hypnos.voice_alignment].trainer_backend`, `[hypnos.voice_alignment].trainer_python`, and `[hypnos.voice_alignment].hot_swap_mode` all live in that section. The shipped defaults are `trainer_backend = "in_process"` and `hot_swap_mode = "manual"`. To run Stage-2 in a separate Python environment, set `trainer_backend = "subprocess"` and point `trainer_python` at that interpreter. On a container host, use `trainer_backend = "job_queue"` with the `kaine-trainer` compose service.

> **Important:** the `[training]` extra requires HuggingFace-format base model weights on disk (not a model-server model id, not a `.gguf` file). Set `[hypnos.voice_alignment].base_model_path` to the directory containing `config.json`, `tokenizer.*`, and `model.safetensors`.

For Qwen3.5 trainer prerequisites, see [Voice alignment](../10-sleep/voice-alignment.md).

## After installing

1. Bring up Redis, Qdrant, and any other services your modules need. See [Supporting services](services.md).
2. Boot the entity. See [First boot](first-boot.md).
3. Open Nexus. With `[nexus].access = "open"` there is no token or sign-in. When conversation is off, the root path `/` redirects to `/diagnostics/`.

The cycle refuses to start if the Lingua organ returns no content, unless you set `KAINE_ALLOW_MUTE_ORGAN=1`.
