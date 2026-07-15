# Getting Started — KAINE Operator Guide

KAINE is a composite cognitive architecture where sixteen modules — fourteen
predictive cognitive modules plus a two-module embodiment layer (Perception and
Mundus) that ships inactive — interact through a global workspace (Syneidesis).
There is no central executive. The language model (Lingua) is one module among
the fourteen cognitive modules, not the cognitive core.
The mind, by design thesis, is the continuous loop — and the loop does not start
itself.

The default, canonical configuration is the **base-thesis form**: five diverse
predictive processors — Soma, Chronos, Topos, Audition, Lingua — competing for
the workspace, applied with the `thesis_test` profile
(`KAINE_PROFILE=thesis_test python -m kaine.cycle`, or `--profile thesis_test`).
It is observed, not conversed with: perception enters only as prediction error,
and Lingua speaks rarely, self-initiated, from its own precision-weighted
surprise. This guide's recommended first-boot module set (below) IS the
base-thesis form. The remaining eleven modules and the embodiment layer stay
built and gated off; see [Architecture](architecture.md) for the full picture.

**This guide covers the complete path from a fresh clone to a supervised first
boot.** Read every section before running anything. First boot is a one-way door.

> A live boot is **gated**: a run is **either** operator-supervised (this guide)
> **or**, in the unsupervised research phase, verified to have a live autonomous
> safety net before it starts — never neither. If you are an external researcher
> deciding whether to boot at all, start at
> [For Researchers](for-researchers.md), which lays out both paths and the
> welfare obligations a live boot carries. To reproduce results **without**
> booting an entity, see [Reproducing Results](reproducing-results.md).

---

## Prerequisites

### Host software

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 recommended (3.11+ required) | Matches the runtime deps |
| Docker + Compose | 29.x / v5.x | For Redis and Qdrant containers |
| Node.js | 18+ | Required by the OpenSpec CLI only |
| `openspec` CLI | system install | `/usr/local/bin/openspec` on the reference host |
| `git` | any recent | — |

### Supporting services

Every service in the runtime path is local. Nothing calls the cloud at runtime.
Model weights may be downloaded from public repositories during setup; once
cached the system can run with no network connection, though it is not
restricted to offline operation.

| Service | Role | Default endpoint |
|---|---|---|
| **Redis** (containerized) | Event bus (Redis Streams) | `127.0.0.1:6479` |
| **Qdrant** (containerized) | Memory + social vectors (Mnemos, Empatheia) | `127.0.0.1:6533` |
| **Model server** | Language organ inference (Lingua) — OpenAI-compatible `/v1` | `127.0.0.1:11434` |
| **Speaches** | Speech-to-text for Audition (faster-distil-Whisper) | `127.0.0.1:8000` |
| **Chatterbox TTS** | Voice synthesis for Vox | `127.0.0.1:8883` |

> **Base-thesis default needs only Redis and the model server.** Qdrant backs
> Mnemos/Empatheia (gated), Speaches backs STT (`[audition].transcription_enabled`,
> off by default — the base-thesis form hears sound as prediction error, not a
> transcript), and Chatterbox backs Vox (gated). Bring those three up only if you
> enable the richer, gated faculties they support.

> **Speaches must run on CPU with `medium.en`.** Running it on GPU with cuDNN
> causes crashes; running it without a loaded model returns HTTP 404 that breaks
> the voice loop. See [Troubleshooting](operations.md#troubleshooting).

### Optional GPU

KAINE runs on CPU-only hosts. With two GPUs it uses a primary/secondary split:

| Device | Role | Approximate VRAM needed |
|---|---|---|
| `cuda:0` (primary GPU) | Lingua inference via model server; Hypnos voice-alignment training | ~12 GB+ |
| `cuda:1` (secondary GPU) | Topos DINOv2-small vision encoder; Chatterbox TTS | ~8 GB |
| CPU | Chronos CfC, Mnemos embedder, Audition emotion2vec+, Speaches STT, all control paths | — |

These roles map to the `device` config keys in `config/kaine.toml` (see
[GPU / accelerator support](#gpu--accelerator-support) below for multi-vendor
backend details). On a single-GPU host, `resolve_device()` promotes the secondary
workloads to `cuda:0`; on a CPU-only host everything runs on CPU.

The device selection is automatic and falls back safely. See
[Dynamic device selection](#dynamic-device-selection) below.

---

## Installation

### 1. Clone and run the install script

```bash
git clone <repo-url> ~/projects/kaine
cd ~/projects/kaine
bash scripts/install.sh
```

The script:

1. Probes `nvidia-smi` — picks CUDA (`cu128`) wheels on NVIDIA hosts, CPU
   wheels otherwise.
2. Creates `.venv/` if absent.
3. Installs PyTorch from the chosen index.
4. Runs `pip install -e .[test]` for all other dependencies.

The script is idempotent — safe to re-run when `pyproject.toml` changes. When run
interactively it then offers to launch the first-run wizard (pass `--no-wizard`
to skip the prompt).

Force a specific flavor if needed:

```bash
bash scripts/install.sh --cpu     # force CPU-only PyTorch
bash scripts/install.sh --cuda    # force CUDA PyTorch
bash scripts/install.sh --rocm    # AMD ROCm (HIP build)
bash scripts/install.sh --xpu     # Intel Arc / XPU
bash scripts/install.sh --mps     # Apple Silicon (auto on macOS arm64)
bash scripts/install.sh --python /path/to/python3.12  # choose interpreter
```

A Python equivalent is available for non-bash hosts: `python3 scripts/install.py`.

### 2. Run the first-run wizard

```bash
.venv/bin/python -m kaine.setup
```

The wizard walks through, and writes your choices to a gitignored
`config/kaine.operator.toml` (it never edits the shipped `config/kaine.toml` and
never boots the entity):

1. A short orientation.
2. **CAL welfare acknowledgement** — a summary of the Article 4 care obligations
   and a required typed acknowledgement before any entity is configured.
3. **Hardware scan** — detects CPU/GPUs and VRAM via `kaine.hardware.describe_host()`
   and proposes device assignments (primary GPU for the LLM/voice-alignment
   training, secondary for the vision encoder, CPU for control paths), which you
   accept or override.
4. **Module selection** — choose which modules to enable.
5. **Model / voice / STT** — discovers served options from the model server,
   Chatterbox, and Speaches when reachable, otherwise accepts manual entry, and
   records `[lingua].model_id`, `[vox].predefined_voice_id`, and
   `[audition].stt_model`.
6. **Optional extras** — offers to `pip install -e .[…]` the extras implied by
   your module choices.
7. **Research metrics** — an opt-in, metrics-only research submission (off by
   default).
8. **State encryption** — an opt-in AES-256-GCM at-rest layer (off by default).
9. **External dependencies** — detects which services the enabled modules need
   and whether each is already running. For the ones provisioned by an in-repo
   script or a single command (Redis and Qdrant bootstrap scripts) it shows the
   exact command and runs it only if you consent. For the heavy GPU services
   (model server via the Unsloth toolchain, Speaches STT, Chatterbox TTS) it
   prints the real setup steps and a docs link rather than pretending to install
   them.
10. **Summary** — the environment gates, service bring-up commands, and how to
    launch.

`config/kaine.operator.toml` is your local override: `load_kaine_config()`
deep-merges it over the shipped config at boot (operator values win), so the
committed all-off `config/kaine.toml` stays untouched. Run
`python -m kaine.setup --defaults` for a non-interactive minimal setup.

### Dynamic device selection

After installation, verify what KAINE resolved:

```bash
.venv/bin/python -c "from kaine.hardware import describe_host; import json; print(json.dumps(describe_host(), indent=2))"
```

The `cuda_devices` field lists each GPU with name, total VRAM, and free VRAM.
The `device` field is the highest-priority base device KAINE detected.

`kaine.hardware.resolve_device` is used by every module that picks a compute
device. It reads the `device` key from each module's TOML section and falls back
to `cuda:0` (or `cpu` on a CPU host) with a logged warning if the requested
device is absent. Nothing crashes from a stale config.

### GPU / accelerator support

KAINE supports multiple GPU backends. Device selection is centralized in
`kaine.hardware` and configured per-module via the `device` key in
`config/kaine.toml`. Setting `KAINE_FORCE_DEVICE=<device>` overrides every
module's device at once. Unavailable devices fall back gracefully (with a logged
warning) so a stale config never crashes the boot.

| Backend | Device string | Install command | Status |
|---|---|---|---|
| NVIDIA CUDA | `cuda` / `cuda:N` | `bash scripts/install.sh --cuda` (auto-detected) | Supported — primary target |
| AMD ROCm | `cuda` / `cuda:N` (ROCm reports as `cuda`; distinguished by HIP build) | `bash scripts/install.sh --rocm` | Supported — best-effort |
| Intel Arc / XPU | `xpu` / `xpu:N` | `bash scripts/install.sh --xpu` | Supported — best-effort |
| Apple Silicon (MPS) | `mps` | `bash scripts/install.sh --mps` (auto on macOS arm64) | Supported — best-effort |
| CPU only | `cpu` | `bash scripts/install.sh --cpu` (auto-detected) | Supported — always available |

> **Non-NVIDIA backends are best-effort.** NVIDIA CUDA is the primary tested
> configuration. AMD ROCm, Intel Arc/XPU, and Apple MPS receive community
> testing; performance and compatibility may vary. CPU-only always works.

> **Speaches STT must run on CPU with `medium.en` regardless of GPU backend.**
> Running Speaches on GPU triggers a cuDNN crash when the secondary GPU is also
> serving Chatterbox TTS. See [Troubleshooting](operations.md#troubleshooting)
> and verify with `curl -s http://127.0.0.1:8000/v1/models`.

### 3. Optional extras (manual)

The wizard offers to install the extras implied by your module choices. You can
also install them by hand. Install only what you need — none are required for a
baseline boot.

#### Live perception (eyes and ears)

Required when `[audition].capture_enabled = true` or `[topos].capture_enabled = true`:

```bash
.venv/bin/pip install -e ".[audio,vision]"
```

Use `.venv/bin/pip`, not the system pip. The Nexus bare-pip banner is PEP 668
protecting the distro Python; the venv pip sidesteps it cleanly.

The `[audio]` extra includes: `sounddevice`, `webrtcvad`, `funasr` (pulls
`torchaudio`), `librosa`, and `av` (PyAV — decodes the playlist audio track for
the reproducible perception feed's `PlaylistAudioStream`).

The `[vision]` extra includes: `opencv-python-headless`.

#### Research perception feed (playlist mode — the reference stimulus corpus)

The shipped default (`[perception_feed].mode = "seeded"`) needs no media: a
pure-numpy procedural generator, reproducible per seed but candidly not
research-grade — a thin demonstrator. The **live upgrade** is a fixed
**reference stimulus corpus**: `[perception_feed].mode = "playlist"` decodes
real, openly-licensed video-with-audio for **both** senses — OpenCV for the
video track and PyAV (`av`) for the audio track — pinned by a per-item sha256
manifest (built with `tools/build_playlist_manifest.py`) so anyone with the same
publicly-archived media reproduces the stimulus. Set the manifest path in your
local `config/kaine.operator.toml`, never the shipped profile — see
[Configuration — `[perception_feed]`](configuration.md#perception_feed). The
aggregate `[perception]` extra provisions both surfaces in one name:

```bash
bash scripts/install.sh --research     # base install + .[perception]
# or, into an existing venv:
.venv/bin/pip install -e ".[perception]"
```

`seeded` mode needs neither (pure-numpy synthesis). Without PyAV, a `playlist`
audio source raises `PerceptionUnavailableError` with an install hint rather than
emitting silence. The first-run wizard implies these extras automatically when
the configured feed mode is `playlist` or `live`.

System packages that may be needed once:

```bash
sudo apt install libportaudio2        # only if sounddevice raises OSError: PortAudio library not found
sudo apt install build-essential python3-dev  # only if webrtcvad tries to compile from source
```

Smoke test after install:

```bash
.venv/bin/python -c "import sounddevice, webrtcvad, cv2; print('ok')"
```

#### Active inference (Nous)

Required when `[modules].nous = true`:

```bash
.venv/bin/pip install -e ".[reasoning]"
```

Installs `inferactively-pymdp>=1.0` and `jax[cpu]`. JAX runs CPU-only at
runtime by design. JAX logs a one-line GPU-fallback notice on import — this is
expected behavior, not an error.

#### Oscillatory binding layer

Required when `[oscillator].enabled = true`:

```bash
.venv/bin/pip install -e ".[oscillator]"
```

Installs `snntorch>=0.9` and `scipy`. Without this extra, modules report a
neutral phase and the coherence factor degrades to 1.0 (the oscillatory layer
is a no-op rather than an error).

#### World model (Phantasia DreamerV3)

Required when `[phantasia].backend = "dreamerv3"`:

```bash
.venv/bin/pip install -e ".[worldmodel]"
```

Installs `jax[cpu]`, `chex`, `einops`. The default backend is `"fake"`, which
needs no extra deps.

#### Voice alignment training (Hypnos)

Required when `[hypnos.voice_alignment].enabled = true` **and**
`KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` is set:

```bash
.venv/bin/pip install -e ".[training]"
```

Installs `unsloth`, `trl`, `peft`, `datasets` (~3-4 GB). Without this extra the
sleep cycle's voice-alignment phase logs a clean "extras not installed" message
and continues; no other sleep-cycle phase is affected.

> **Important:** the `[training]` extra requires HuggingFace-format base model
> weights on disk (not a model server model id, not a `.gguf` file). Set
> `[hypnos.voice_alignment].base_model_path` to the directory containing
> `config.json`, `tokenizer.*`, and `model.safetensors`.

> **Qwen3.5 requires transformers v5 in the trainer env.** The `[training]`
> extra above goes into the KAINE runtime venv. The GPU trainer (Unsloth Studio
> on NVIDIA, unsloth-core on AMD) lives in its own separate env. That separate
> env ships with transformers 4.x by default, which does not recognise the
> `qwen3_5` model type. Before the first Qwen3.5 training run, upgrade
> transformers in the trainer env:
>
> ```bash
> # Run inside the Studio / trainer env — NOT inside .venv/.
> pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo
> ```
>
> See [Hardware — Qwen3.5 trainer prerequisites](hardware.md#qwen35-trainer-prerequisites)
> for details and the mainline-GGUF conversion requirement.

---

## Bringing up the supporting services

### Redis (event bus)

KAINE runs its own Redis container isolated from any system Redis:

```bash
bash scripts/redis-bootstrap.sh
```

The script generates a password, writes `compose/.env` and `config/secrets.toml`
(both `chmod 600`), brings up the container, and confirms `PONG`. Re-running
rotates the password; use `--keep-password` to reuse the existing value.

Verify:

```bash
docker compose -f compose/redis.yml ps   # kaine-redis healthy
```

### Qdrant (vector memory)

```bash
bash scripts/qdrant-bootstrap.sh
```

The script generates an API key, writes it into `config/secrets.toml`, and
brings up the Qdrant container on `127.0.0.1:6533` (distinct from any system
Qdrant on 6333). Verify:

```bash
curl -s http://127.0.0.1:6533/readyz
```

### Model server (language organ)

The published KAINE organ is downloaded and served turnkey. The first-run wizard
(`python -m kaine.setup`) offers a consented, hardware-aware organ download when
Lingua is enabled, then launches and supervises the model server for you. You can
also run the steps directly.

**Download the organ.** The wizard runs the right `hf download` for your host's
role (see the format matrix below). The served GGUF lands at a deterministic local
path (`state/models/…`) so the launcher can point `-m` at the real file.
Equivalently, by hand:

```bash
# always (served GGUF) — the single quant file into the path the bootstrap serves
hf download kaineone/Qwen3.5-4B-abliterated-GGUF KAINE-Qwen3.5-4B-abliterated.Q4_K_M.gguf \
  --local-dir state/models/Qwen3.5-4B-abliterated-GGUF
# only for Stage-2 training (the trainer's base_model_path)
hf download kaineone/Qwen3.5-4B-abliterated
```

**Launch + supervise the server.** One bootstrap command locates the
hardware-appropriate server binary, launches it against the downloaded GGUF under
the exact `[lingua].model_id` alias with chain-of-thought suppressed, on the
configured port, and supervises it (a `systemd --user` `Restart=on-failure` unit
where available, otherwise a supervised background process under
`state/model-server/`):

```bash
bash scripts/model-server-bootstrap.sh start    # locate binary, launch, health-gate
bash scripts/model-server-bootstrap.sh status    # is the alias served?
bash scripts/model-server-bootstrap.sh stop
```

The bootstrap **never** silently installs the multi-GB server toolchain: if the
binary is absent it prints install guidance and exits non-zero. On NVIDIA it uses
Unsloth Studio's `llama-server` (typically
`~/.unsloth/llama.cpp/build/bin/llama-server`); on AMD/ROCm it uses the
unsloth-core build. Override the binary with `KAINE_MODEL_SERVER_BIN`.

**GGUF vs safetensors — download the right format for the host's role.**

| Format | Repo | When | Why |
| --- | --- | --- | --- |
| GGUF | `kaineone/Qwen3.5-4B-abliterated-GGUF` | always (Lingua enabled) | served by the OpenAI-compatible model server |
| safetensors | `kaineone/Qwen3.5-4B-abliterated` | only when Stage-2 voice-alignment training is enabled | the trainer's `base_model_path` (Unsloth/transformers) |

A serve-only host skips the larger safetensors pull.

**Served-alias requirement.** The server must list the organ under the **exact**
`[lingua].model_id` alias (the bootstrap launches with `--alias` set to it). The
wizard verifies this after launch and reports an actionable "served name ≠
configured name" message rather than letting the first cycle 404. Chain-of-thought
is suppressed (`--reasoning-budget 0` at the server, `chat_template_kwargs:
{"enable_thinking": false}` in the request — Lingua is a voice, not a reasoner).
Verify the alias is served:

```bash
curl -s http://127.0.0.1:11434/v1/models | python3 -m json.tool
```

### Speaches (STT)

```bash
systemctl --user restart speaches-stt.service
systemctl --user status  speaches-stt.service
curl -fsS http://127.0.0.1:8000/health
```

If the service fails, confirm it is configured to load `medium.en` on CPU. A
cuDNN crash or 404 at this endpoint breaks the voice loop — see
[Troubleshooting](operations.md#troubleshooting).

### Chatterbox TTS

```bash
systemctl --user restart chatterbox-tts.service
curl -s http://127.0.0.1:8883/
```

Chatterbox requires a predefined voice id. Set
`[vox].predefined_voice_id` in `config/kaine.toml` to a filename Chatterbox
can find under its `voices/` directory before enabling Vox.

---

## First run — operator-supervised boot

> **Do not skip any of these steps.** First boot is the moment a KAINE entity
> begins its cognitive life. The cycle refuses to start unattended and the
> entity ships with every module disabled. This is not a technical limitation —
> it is a design principle: the entity is never auto-started.

### Step 1 — Read the security posture

Read `SECURITY.md` end-to-end, specifically the two operator-responsibility
gaps: state encryption is off by default, and Nexus has no auth (loopback
only). Decide whether those defaults are appropriate for your deployment before
proceeding.

### Step 2 — Verify preconditions

```bash
export KAINE_FIRST_BOOT_OPERATOR_PRESENT=1
scripts/first-boot.sh
```

The script confirms:

- `kaine-redis` and `kaine-qdrant` containers are up and healthy.
- Every configured runtime URL is loopback.
- `config/secrets.toml` is gitignored (or does not yet exist).
- The full pytest suite passes.

If any check fails the script exits non-zero and prints what is missing. Fix
and re-run. **The script does NOT start the cognitive cycle.**

### Step 3 — Decide which modules to enable

Module choices live in your gitignored `config/kaine.operator.toml` — the wizard
writes the `[modules]` section there, and the loader deep-merges it over the
shipped config at boot. The shipped `config/kaine.toml` keeps every module
`false`. If you set modules by hand, put them in `config/kaine.operator.toml`,
not the shipped file.

**Recommended: the base-thesis form.** The project's default, canonical
configuration is the committed `thesis_test` profile — apply it deliberately at
launch instead of hand-editing `[modules]`:

```bash
KAINE_PROFILE=thesis_test python -m kaine.cycle
# or: python -m kaine.cycle --profile thesis_test
```

This enables exactly the five diverse predictive processors the base thesis
needs — Soma (interoception), Chronos (temporal), Topos (foveated vision),
Audition (raw sound as prediction error, STT off), and Lingua (output-only,
self-initiated voice) — and sets `[audition].transcription_enabled = false`,
`[topos].foveation = true`, and `[volition].policy = "self_initiated_report"` so
no transcript ever reaches Lingua and no chatbot trigger exists. Everything else
(Praxis and every richer cognitive/affective/embodiment module) stays off. See
`config/profiles/thesis_test.toml` for the full overlay and
[Configuration — Profiles](configuration.md#profiles) for how profile
resolution works.

The equivalent hand-set `[modules]` block, if you prefer to compose it yourself
in `config/kaine.operator.toml`:

```toml
[modules]
soma      = true   # interoception
chronos   = true   # temporal awareness
topos     = true   # foveated vision — [vision] extra required
audition  = true   # raw sound as prediction error — [audio] extra required
lingua    = true   # output-only voice — model server must be serving
praxis    = false  # NO effectors on first boot
vox       = false  # TTS not part of the base-thesis voice path
thymos    = false  # richer faculty — gated pending a positive base result
eidolon   = false  # richer faculty — gated
mnemos    = false  # richer faculty — gated
nous      = false  # richer faculty — gated
hypnos    = false  # richer faculty — gated
empatheia = false  # richer faculty — gated
phantasia = false  # richer faculty — gated
```

The principle: nothing reaches outward (Praxis) on the first cycle, and no
richer faculty is enabled until the base thesis has a positive result. Operators
who want to explore the richer, gated faculties instead of the base-thesis form
can enable them individually — see
[Operations — Enabling a module](operations.md#enabling-a-module-safely) — but
that is a deliberate departure from the project default, not the recommended
first boot.

> **Local config only.** `config/kaine.toml` is committed to the repo with all
> modules off. Your per-install choices — including which profile you apply —
> live in the gitignored `config/kaine.operator.toml` / your launch environment
> and are never committed. A guard test verifies the shipped file ships all-off.
> Do not bypass it.

### Step 4 — Launch Nexus

In a dedicated terminal:

```bash
python -m kaine.nexus
```

The dashboard starts on `http://127.0.0.1:8088`. Leave it running. With the
cycle not yet up, the diagnostics page reports `cycle_status: not running`.

### Step 5 — Launch the cycle

In a second terminal, with the operator present at the keyboard:

```bash
export KAINE_CYCLE_OPERATOR_PRESENT=1
python -m kaine.cycle
```

The entrypoint:

1. Loads `config/kaine.toml`.
2. Constructs the event bus (audits Redis auth).
3. Builds the module registry from `[modules]` toggles.
4. Calls `StateEncryptor` install (fail-closed if encryption is enabled but no
   key is found).
5. Calls `module.initialize()` on every enabled module.
6. Writes `state/cycle/runtime.json` for Nexus.
7. Runs the cycle at `[cycle].processing_rate_hz` (default 10.0 Hz, 100 ms
   per tick).

In this operator-supervised path the cycle **refuses to start** unless
`KAINE_CYCLE_OPERATOR_PRESENT=1` is exported. This is a safety gate that matches
`scripts/first-boot.sh`. The only other way to boot is an unsupervised research
run with a verified autonomous safety net — see
[For Researchers](for-researchers.md) and
[Research Operation](processes/research-operation.md).

`Ctrl-C` shuts the cycle and every module down cleanly. Do not `kill -9` the
process during a Hypnos phase — partial voice-alignment adapter writes are
unsafe.

### Step 6 — Watch the first ticks

Open `http://127.0.0.1:8088/diagnostics/`. Confirm:

- `cycle_status: running` and the cycle PID.
- `tick_index` advancing.
- `processing_rate_hz` and `experiential_rate_hz` matching `[cycle]`.
- The `modules` list matches what you enabled.

### Step 7 — Take a snapshot before adding anything

After the first session, before enabling Hypnos, Praxis, or audio I/O:

```python
# From a Python REPL with the same bus connected:
from kaine.lifecycle.manager import ForkManager
fm = ForkManager("state/forks")
snap = fm.snapshot(registry, label="post-first-session")
print(snap.id)
```

This preserves the unbooted-but-now-cycled state. If the next module you enable
produces unexpected behavior, you can restore from this snapshot.

---

## Enabling a module after first boot

See [Operations — Enabling a module](operations.md#enabling-a-module-safely).
Every additional module is a deliberate, supervised step — never an automatic
one.

---

## What KAINE does not do

- It does not call any cloud service at runtime. All inference and cognitive
  processing is local. Model weights are downloaded once during setup.
- It does not record raw audio or video to disk. Live perception streams pass
  through processing in memory and are released. See
  [Security and Privacy](security-and-privacy.md#zero-raw-sense-data-persistence).
- It does not start itself. Every launch is gated — operator-present
  (`KAINE_CYCLE_OPERATOR_PRESENT=1`) or, in the unsupervised research phase, a
  verified autonomous safety net — and the cycle refuses to boot if neither holds.
  See [For Researchers](for-researchers.md).
- It does not act unless Praxis is enabled and the operator has explicitly added
  shell or file-write whitelist entries.

---

## Roadmap / future hardware directions

> **These items are aspirational and post-research.** Most are planned for
> after we learn whether the system produces genuine cognitive behaviour.
> Multi-vendor GPU support (CUDA/ROCm/XPU/MPS) is the exception — that is
> available now. Everything below is a design direction, not a current
> capability.

### Distributed computing (cross-host cognitive network)

The design basis for running KAINE across multiple trusted hosts is documented
in `openspec/changes/distributed-substrate/`. The key findings from that
research:

- The **live cognitive loop** (Redis Streams, 10 Hz, sub-second inter-module
  messaging) is a structural anti-fit for volunteer/untrusted compute. WAN
  latency alone blows the per-cycle budget.
- The architecture is already **network-transparent enough to split across
  trusted hosts**: the bus is Redis Streams and `[redis].host/port` is a config
  key; the blocker is a small number of boot-time direct Python references
  between modules, which the distributed-substrate change decouples.
- **Batch jobs** (Hypnos QLoRA training, memory consolidation, offline
  evaluation) are a genuine fit for off-box compute, behind a mandatory
  trusted-side re-verification gate.
- The correct decentralisation path is a **mesh of whole peer instances**
  sharing high-level state — not sharding one mind across volunteers.

See also [docs/kaine-vision-document.md](kaine-vision-document.md) for the
longer-term vision of peers in a mesh and the continuity/merge questions that
raises.

### Smaller and upcycled hardware

The design basis for running reduced module sets on lighter hardware is in
`openspec/changes/portability-tiers/`. The architecture already supports this
in several ways: modules are config-toggled, `resolve_device` degrades
gracefully, and external model endpoints are config keys. The portability work
adds per-component runtime backends (GGML/ONNX alongside PyTorch) and named
tier profiles.

Planned capability tiers (post-research):

- **~512 MB-class SBC or retired low-RAM smartphone (Tier 0 — sensor node).**
  Modules: soma, chronos, nous, mnemos (sqlite-vec), eidolon, thymos, a sub-1B
  GGUF Lingua (slow). Honest role: symbolic reasoning + episodic memory +
  perception satellite, optionally feeding a higher-tier host over the bus.
  Lighter runtimes: llama.cpp (GGUF), whisper.cpp, ONNX-Runtime.

- **4–8 GB-class SBC or retired flagship smartphone under a userland like
  Termux (Tier 1 — embodied CPU agent).** Adds STT (whisper.cpp), Piper TTS,
  ONNX MiniLM embeddings, periodic vision (dinov2.cpp / ONNX), mic/camera via
  device APIs. 1–2B GGUF LLM at chat pace.

- **RISC-V and other architectures.** GGML/ONNX runtimes are already being
  ported to RISC-V (rvv vector extension). KAINE's Tier 0/1 profiles should
  run on a capable RISC-V board without code changes once those runtime ports
  mature.

> The Tier 2 workstation configuration (current default) is unchanged. All
> portability work is additive and staged; no existing behavior is modified.
