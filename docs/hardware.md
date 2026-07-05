# Hardware Reference

This page consolidates KAINE's hardware requirements in one place. The two paths
from [For Researchers](for-researchers.md) have very different needs: reproducing
results offline (Path A) is light; booting a live entity (Path B) is heavier
because it runs the language organ and the supporting services.

KAINE's device selection is dynamic and falls back safely, so a stale config
never crashes a boot. For the install-time accelerator flags and the per-module
`device` keys, see
[Getting Started — GPU / accelerator support](getting-started.md#gpu--accelerator-support)
and [Dynamic device selection](getting-started.md#dynamic-device-selection); the
detection logic lives in `kaine/hardware.py`.

---

## Requirements by path

| | Path A — offline reproduction | Path B — live entity boot |
|---|---|---|
| **GPU** | None required | One GPU recommended for the language organ; CPU-only works (slower) |
| **VRAM** | — | ~8 GB+ on one GPU for the 4B organ |
| **Supporting services** | None | Redis, model server, Qdrant (+ Speaches/Chatterbox only for voice) |
| **Python** | 3.12 recommended (3.11+ required) | 3.12 recommended (3.11+ required) |
| **What runs** | Test suite + offline runners/benchmarks | The full cognitive cycle |

The offline path drives deterministic / echo clients and in-memory stores; it
needs no accelerator and no services. Everything below concerns a live boot.

---

## GPU and VRAM guidance (Path B)

KAINE runs on a single GPU, two GPUs, or CPU-only. Roles map to per-module
`device` keys in `config/kaine.toml`, and `resolve_device()` adapts to what is
actually present.

- **Language organ (Lingua).** The published KAINE abliterated organ
  (`kaineone/Qwen3.5-4B-abliterated-GGUF`, served via a local OpenAI-compatible
  model server) fits a single small GPU comfortably. A GPU with more headroom
  (≈12 GB+) hosts the organ alongside the optional Hypnos voice-alignment training
  (which uses the `kaineone/Qwen3.5-4B-abliterated` safetensors base). Operators
  with more capable hardware can configure a larger organ locally.
- **Vision (Topos).** When vision is enabled, the DINOv2-small encoder
  (`facebook/dinov2-small`) can share the organ's GPU or, on a two-GPU host, run
  on a **secondary GPU** (≈8 GB class) so it does not contend with the organ.
- **Single-GPU host.** `resolve_device()` promotes the secondary workloads onto
  the primary GPU. The organ plus an enabled vision encoder must then fit within
  that one card's VRAM.
- **CPU-only fallback.** Everything runs on CPU when no accelerator is present —
  the system is fully functional but the language organ and any neural perception
  are **substantially slower**. This is the right choice for exploring the
  architecture without a GPU; it is not the right choice for live-pace
  interaction.
- **CPU-resident components.** Several components always run on CPU regardless of
  GPU: the Chronos CfC temporal model, the Mnemos embedder, the Audition emotion
  model and STT, and all control paths.

### Accelerator backends

CUDA is the primary tested backend. ROCm (AMD), XPU (Intel Arc), and MPS (Apple
Silicon) are supported best-effort; CPU-only always works. The installer
auto-detects the backend and can be forced per host. `KAINE_FORCE_DEVICE=<device>`
overrides every module's device at once. Full backend table and install commands:
[Getting Started — GPU / accelerator support](getting-started.md#gpu--accelerator-support).

### Verify what KAINE detected

```bash
.venv/bin/python -c "from kaine.hardware import describe_host; import json; print(json.dumps(describe_host(), indent=2))"
```

`describe_host()` reports the detected base `device`, the backend
(`cuda`/`rocm`/`xpu`/`mps`/`cpu`), and a `cuda_devices` list with each GPU's name,
total VRAM, and free VRAM — the same probe the first-run wizard uses to propose
device assignments.

### Pre-boot GPU headroom check

When `[gpu_preflight].enabled = true`, the cycle verifies VRAM headroom **before**
opening the bus or any module, and refuses to boot (exit code `4`) on a starved
host rather than OOM-killing a just-spawned entity mid-init. The pre-flight is
report-only: it queries `/v1/models` on the model server to report what is
resident, reports other GPU consumers, and never terminates a process.

---

## Supporting services and their footprint (Path B)

A live boot expects these local services. Vision and voice services are only
needed when those modules are enabled; the baseline thinking entity needs only
Redis, the model server, and Qdrant. None call the cloud at runtime.

| Service | Role | Footprint |
|---|---|---|
| **Redis** (containerized) | Event bus (Redis Streams) | Light; CPU/RAM only |
| **Model server** (OpenAI-compatible) | Language organ inference (Lingua) | The 4B organ's VRAM (~8 GB+) when loaded |
| **Qdrant** (containerized) | Vector memory (Mnemos, Empatheia) | Light; grows with stored memories |
| **Speaches** (optional) | Speech-to-text (Audition) | **CPU with `medium.en`** — must not run on GPU |
| **Chatterbox** (optional) | Voice synthesis (Vox) | GPU-served TTS; can share the secondary GPU |

> Speaches STT must run on CPU with the `medium.en` model. Running it on GPU
> triggers a cuDNN crash when the secondary GPU is also serving Chatterbox; a
> missing model returns HTTP 404 that breaks the voice loop. See
> [Getting Started — Speaches](getting-started.md#speaches-stt) and
> [Operations — Troubleshooting](operations.md#troubleshooting).

For bring-up commands and verification, see
[Getting Started — Bringing up the supporting services](getting-started.md#bringing-up-the-supporting-services).

---

## Voice-alignment trainer by GPU vendor

The optional sleep-cycle voice-alignment trainer (Hypnos) runs unsloth in a
SEPARATE external environment, not in the entity-runtime venv. Which unsloth a
host needs depends on the GPU vendor reported by `describe_host()["backend"]`:

| Detected backend | Trainer | Notes |
|---|---|---|
| `cuda` (NVIDIA) | **Unsloth Studio** | Self-contained env; interpreter typically at `~/.unsloth/studio/.../bin/python` |
| `rocm` (AMD) | **unsloth-core** | Studio targets NVIDIA; per unsloth's docs AMD GPUs use unsloth-core in a separate ROCm env |
| `xpu` / `mps` / `cpu` | none | No GPU trainer — voice-alignment training is unavailable; the phase stays off and the consolidation-divergence metric still emits without training |

The first-run wizard (`python -m kaine.setup`) surfaces this as an optional
Stage-2 step: it reads the detected backend, prints the vendor-appropriate
install guidance, and runs a real probe (does the candidate interpreter exist
and can it `import unsloth`?). It never auto-installs the multi-GB trainer env
and never records an interpreter the probe could not verify. When a usable
interpreter is found it offers to set `[hypnos.voice_alignment].trainer_python`
(and `trainer_backend = "subprocess"`) in `config/kaine.operator.toml`. See
[Process: Voice Alignment — Trainer backends](processes/voice-alignment.md#trainer-backends-in-process-vs-out-of-process).

### Qwen3.5 trainer prerequisites

Two additional requirements apply when training against a Qwen3.5 base model:

**transformers v5 in the trainer env.** Unsloth Studio ships with transformers
4.x by default. The `qwen3_5` model type is only recognised from transformers
v5 onwards; there is no `trust_remote_code` fallback (the repos ship no custom
modeling code). After installing Unsloth Studio, upgrade transformers inside
its env before the first training run:

```bash
# Run this inside the Studio env, not the KAINE venv.
pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo
```

This pulls transformers v5 as a dependency. Use `pip install` directly rather
than `unsloth studio update`, because the Studio update command re-triggers a
buggy llama.cpp prebuilt step (`--simple-policy` arg error) that silently
degrades to CPU-only. The force-reinstall may shift torch from a cuXXX build to
a PyPI default build (e.g. cu130→cu128) — that is functional and
forward-compatible, not a problem.

**Mainline llama.cpp GGUF conversion.** Ollama's internal GGUF converter
produces a non-standard `qwen35.rope.dimension_sections` layout that mainline
llama.cpp and Unsloth Studio cannot load (length mismatch error). Export
Qwen3.5 HF weights with `convert_hf_to_gguf.py` from the mainline
[ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp) repo. Do not
copy GGUFs from Ollama's blob store for use outside Ollama.

---

## Lighter and larger hardware

The architecture is config-toggled and device-adaptive, so reduced module sets
run on lighter hardware and operators with more capable machines can scale the
organ up. Planned portability tiers (SBC / smartphone / RISC-V profiles with
GGML/ONNX runtimes) are a post-research design direction documented under
[Getting Started — Smaller and upcycled hardware](getting-started.md#smaller-and-upcycled-hardware).
