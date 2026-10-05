# Hardware

This page covers host sizing, GPUs, accelerators, services footprint, and the voice-alignment trainer for KAINE. Read it when you are choosing hardware, planning a deployment, or sizing a host for a live entity boot. It complements the two research paths described in [For researchers](../14-for-researchers.md).

KAINE's hardware needs split into two paths. Reproducing results offline (Path A) is light and needs no GPU or services. Booting a live entity (Path B) runs the language organ and local services, so it needs more resources. For the install-time accelerator flags and the per-module `device` keys, see [Getting started](../04-getting-started/README.md) and [Accelerators](./accelerators.md). The detection logic lives in [`kaine/hardware.py`](../../kaine/hardware.py).

## Requirements by path

| | Path A — offline reproduction | Path B — live entity boot |
|---|---|---|
| GPU | None required | One GPU recommended for the language organ; CPU-only works (slower) |
| VRAM | — | Enough for the served organ and enabled modules; the shipped config budgets about 3 GB for the 4B organ |
| Supporting services | None | Redis, model server, Qdrant (voice services only if Audition/Vox are enabled) |
| Python | 3.12 recommended (3.11+ required) | 3.12 recommended (3.11+ required) |
| What runs | Test suite + offline runners/benchmarks | The full cognitive cycle |

Path A uses deterministic clients and in-memory stores. Everything below is for Path B.

## Device selection and restrictions

KAINE picks devices dynamically. `resolve_device()` in [`kaine/hardware.py`](../../kaine/hardware.py) maps each module's configured `device` to what is actually present, and a stale config never crashes a boot. You can override or restrict selection with:

- `KAINE_FORCE_DEVICE=<device>` — overrides every module's device at once.
- `[hardware].allowed_devices` and `cpu_threads` in the merged config — limit which devices KAINE may use and how many CPU threads the torch stack may claim. The first-run wizard writes these to `config/kaine.operator.toml`; there is no `[hardware]` table in the shipped base config.
- `[hardware.devices]` with `organ` and `vision` keys — mirrors `topos.device` and the training device choice, so it does not assign devices itself. The first-run wizard uses `device_step` in [`kaine/setup/hardware_steps.py`](../../kaine/setup/hardware_steps.py) to propose values.

On a two-GPU host the secondary GPU can run vision or other non-organ work. On a single-GPU host `resolve_device()` promotes those workloads onto the primary GPU, so the organ plus any enabled vision encoder must fit together.

CPU-only hosts run everything on CPU. The cycle is fully functional but the organ and neural perception are much slower. CPU-only is fine for exploring the architecture; it is not the right choice for live-pace interaction.

Several workloads stay on CPU even when a GPU is present: the Chronos CfC temporal model, Soma's NumPy CfC network, the Audition emotion model and STT, and all control paths. The shared `[embedding]` instance also stays on CPU by default; set `[embedding].backend = "sentence_transformers"` to move it to torch.

## GPU and VRAM guidance (Path B)

### Language organ

The published KAINE abliterated organ (`kaineone/Qwen3.5-4B-abliterated-GGUF`, served by a local OpenAI-compatible model server) is the largest single consumer. The shipped config budgets about 3 GB of VRAM for the served 4B organ (actual usage is unverified). If you have more VRAM, you can configure a larger organ locally.

### Vision

When vision is enabled, the default encoder is InternVideo-Next (`encoder_backend = "internvideo_next"` in [`config/kaine.toml`](../../config/kaine.toml)). DINOv2-small is the alternative. The encoder can share the organ's GPU, or, on a two-GPU host, run on a secondary GPU so it does not contend with the organ.

### Single-GPU host

On a single GPU the organ and any enabled vision encoder must fit together. A 4B LoRA voice-alignment training step is budgeted at about 9.8 GB, so it does not fit alongside the served organ on a single 12 GB card. Hypnos training time-shares the GPU with inference rather than running alongside it.

### Accelerator backends

CUDA is the primary tested backend. ROCm, XPU (Intel Arc), and MPS (Apple Silicon) are supported best-effort; CPU-only always works. The installer auto-detects the backend and can be forced per host. The full backend decision table, wheel indexes, and install commands are on the [Accelerators](./accelerators.md) page.

### Verify what KAINE detected

```bash
.venv/bin/python -c "from kaine.hardware import describe_host; import json; print(json.dumps(describe_host(), indent=2))"
```

`describe_host()` reports the base `device`, the backend, and a `cuda_devices` list with each GPU's name, total VRAM, and free VRAM. The first-run wizard uses the same probe to propose device assignments.

### Keeping the torch stack coherent

The installers read the torch requirement from `pyproject.toml` and install `torch` and `torchvision` together from the resolved wheel index. With `--research`, `torchaudio` is installed from the same index first. After the core stack is in place, the installers write the installed `torch`, `torchvision` and `torchaudio` versions to `<venv>/kaine-torch-constraints.txt` and pass it with `-c` to every later `pip install`, so extras and later resolves cannot swap the stack.

`KAINE_VENV_DIR` selects the virtualenv directory; the default is `.venv`.

The pre-boot sweep (`python -m kaine.preboot`) reports a "Torch stack" row and fails when a companion was built for a different torch or when wheels come from different indexes (for example `torch +cu130` with `torchaudio +cu128`). The installers also fail their verify step on the same condition. The fix is to re-run `scripts/install.sh`. The check reads each package's `version.py` for the build tag because pip metadata can omit it.

### Pre-boot GPU headroom check

When `[gpu_preflight].enabled = true`, the cycle checks accelerator memory headroom before it opens the bus or any module. It refuses to boot (exit code `4`) on a starved host rather than OOM-killing a just-spawned entity mid-init. The pre-flight is report-only: it queries `/v1/models` on the model server, reports other GPU consumers, and never terminates a process.

The gate classifies each host's accelerator memory as known-discrete, known-unified, or unknown. On discrete hosts the `min_free_vram_gb` threshold is applied per device; on unified-memory hosts the same threshold is applied to available system memory. When memory state is unknown the gate always passes and annotates the report.

### Organ idle unload

The model server can unload the organ after it has been idle for `[lingua].model_server_sleep_idle_seconds` seconds. The default is `600`; set it to `-1` to keep the organ loaded. This frees the organ's VRAM after the configured idle period. The setting is passed to the model server as `--sleep-idle-seconds`. For the exact wiring see [`kaine/organ_server/lifecycle.py`](../../kaine/organ_server/lifecycle.py) and [`compose/kaine.yml`](../../compose/kaine.yml).

## Supporting services and their footprint (Path B)

A live boot expects these local services. Voice services are only needed when Audition or Vox is enabled; the baseline thinking entity needs Redis, the model server, and Qdrant. None call the cloud at runtime.

| Service | Role | Footprint |
|---|---|---|
| Redis | Event bus (Redis Streams) | Light; CPU/RAM only |
| Model server | Language organ inference (Lingua) | The served organ's VRAM (about 3 GB in the shipped config) when loaded |
| Qdrant | Vector memory (Mnemos, Empatheia) | Light; grows with stored memories |
| Speaches (optional) | Speech-to-text (Audition) | CPU with `medium.en`; must not run on GPU |
| Chatterbox (optional) | Voice synthesis (Vox) | GPU-served TTS; can share the secondary GPU |

> Speaches STT must run on CPU with the `medium.en` model. Running it on GPU triggers a cuDNN crash when the secondary GPU is also serving Chatterbox; a missing model returns HTTP 404 that breaks the voice loop. See [Getting started](../04-getting-started/README.md) and [Troubleshooting](../06-operation/troubleshooting.md).

As an alternative to Speaches and Chatterbox, Audition and Vox can use sherpa-onnx. Set `[audition].backend = "sherpa_onnx"` and `[vox].backend = "sherpa_onnx"`, and run `python -m kaine.setup.speech_models` to fetch the models.

If a service is shared with another entity or managed outside KAINE, set `[services.<name>].shared = true`. The pre-flight in [`kaine/cycle/preflight.py`](../../kaine/cycle/preflight.py) respects that flag and does not demand an exclusive instance.

### State and service paths

`[storage].data_root` in [`config/kaine.toml`](../../config/kaine.toml), or the `KAINE_DATA_ROOT` environment variable, changes where native service state lives. Native service configs live under `<data root>/state/services` when a data root is set, otherwise under `state/services/`. The pre-boot sweep also checks disk availability; see the `[storage]` and `[preboot]` rows in [`config/kaine.toml`](../../config/kaine.toml).

## Voice-alignment trainer by GPU vendor

The optional sleep-cycle voice-alignment trainer (Hypnos) runs unsloth in a separate environment, not the entity-runtime venv. Which unsloth a host can use depends on the GPU vendor reported by `describe_host()["backend"]`:

| Detected backend | Trainer | Notes |
|---|---|---|
| `cuda` (NVIDIA) | Unsloth Studio | Self-contained env; interpreter at `~/.unsloth/studio/.../bin/python` |
| `rocm` (AMD) | unsloth-core | Studio targets NVIDIA; per unsloth's docs AMD GPUs use unsloth-core in a separate ROCm env |
| `xpu` / `mps` / `cpu` | none | No GPU trainer; voice-alignment training is unavailable. The phase stays off and the consolidation-divergence metric still emits without training |

On native hosts the trainer is driven with `trainer_backend = "subprocess"` and a `trainer_python` path. On container hosts use `trainer_backend = "job_queue"` with the `kaine-trainer` compose service. `trainer_backend` defaults to `"in_process"` and the default `hot_swap_mode` is `"manual"`; it is forced to manual when a model server is shared. See [`config/kaine.toml`](../../config/kaine.toml). For details see [Voice alignment](../10-sleep/voice-alignment.md).

The first-run wizard (`python -m kaine.setup`) surfaces the trainer as an optional Stage-2 step. It reads the detected backend, prints vendor-appropriate guidance, and probes the candidate interpreter with `import unsloth`. It never auto-installs the multi-GB trainer env and never records an interpreter the probe could not verify. When a usable interpreter is found, it offers to set `[hypnos.voice_alignment].trainer_python` and `trainer_backend = "subprocess"` in `config/kaine.operator.toml`.

### Qwen3.5 trainer prerequisites

Two extra requirements apply when training against a Qwen3.5 base model.

**transformers v5 in the trainer env.** Unsloth Studio ships with transformers 4.x by default. The `qwen3_5` model type is only recognised from transformers v5 onwards; there is no `trust_remote_code` fallback. After installing Unsloth Studio, upgrade transformers inside its env before the first training run:

```bash
# Run this inside the Studio env, not the KAINE venv.
pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo
```

This pulls transformers v5 as a dependency. Use `pip install` directly rather than `unsloth studio update`, because the Studio update command re-triggers a buggy llama.cpp prebuilt step (`--simple-policy` arg error) that silently degrades to CPU-only. The force-reinstall may shift torch from a cuXXX build to a PyPI default build (for example cu130 to cu128) — that is functional and forward-compatible, not a problem.

**Mainline llama.cpp GGUF conversion.** Ollama's internal GGUF converter produces a non-standard `qwen35.rope.dimension_sections` layout that mainline llama.cpp and Unsloth Studio cannot load (length mismatch error). Export Qwen3.5 HF weights with `convert_hf_to_gguf.py` from the mainline [ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp) repo. Do not copy GGUFs from Ollama's blob store for use outside Ollama.

## Lighter and larger hardware

The default `[embedding]` backend uses a shared NumPy MiniLM embedder, so Mnemos, Empatheia, and Hypnos do not load torch unless you set `[embedding].backend = "sentence_transformers"`. Soma and Chronos run their CfC networks on NumPy by default, Nous can use `backend = "numpy"`, and Phantasia can use `engine = "numpy"`. Audition and Vox can use `sherpa_onnx` instead of the Speaches/Chatterbox services.

The edge tier profiles reduce the active module set and swap heavy backends to lighter ones:

- `tier0.toml` disables Topos, Audition, Vox, Empatheia, and Phantasia, and marks them as unsupported modules with `oscillator_supported = false`.
- `tier1.toml` keeps most modules but swaps Audition and Vox to `backend = "sherpa_onnx"`, Nous to `backend = "numpy"`, Phantasia to `engine = "numpy"`, blanks the emotion model ID, sets Topos `device = "cpu"`, Lingua to the `llama_cpp` backend, and Mnemos to `sqlite_vec`.

Tier profiles cannot toggle modules directly; they change defaults and backend selections. Tier definitions and deployment trade-offs are in [Choosing a deployment](../07-deployment/README.md); current capability lists are in [Getting started](../04-getting-started/README.md).

On hosts that cannot sustain the processing rate, set `auto_time_scale = true` to slow subjective time instead of distorting the dynamics. The long-term portability plan — NumPy CfC core, sherpa-onnx speech, NumPy Nous/Phantasia, Termux and thin-client offload, arm64 images, and multi-node residency — is recorded in the archived portability-tiers spec at [`openspec/changes/archive/2026-09-17-portability-tiers`](../../openspec/changes/archive/2026-09-17-portability-tiers).
