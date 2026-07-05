## Why

KAINE was designed for a two-GPU host. `docs/kaine-paper.md` §6.1
calls for "at least 12 GB VRAM on the primary GPU for LLM inference,
a secondary GPU with at least 8 GB for the world model encoder."
`SETUP.md` §1.4 records the operator-confirmed allocation:

- RTX 4070 SUPER (12 GB) — Lingua inference (Unsloth Studio) + voice
  alignment training (Hypnos)
- RTX 3070 (8 GB)        — Topos vision encoder + Chatterbox + Speaches

The code did not honor that intent. `kaine/hardware.py::select_device`
returns only `"cuda"` / `"mps"` / `"cpu"` — there is no way to target
`cuda:1`. Every module that asked for a GPU got `cuda:0`. So the
secondary GPU was idle and `cuda:0` was over-shared between Topos
inference and Mnemos embeddings (and would be hit again by Hypnos
training when that path lands).

This change makes the original allocation real. It also adds boot-time
visibility (so the operator can see which module landed where) and
sensible CPU-thread tuning (so concurrent CPU inference doesn't
oversubscribe a 32-thread Ryzen).

## What Changes

- `kaine/hardware.py`:
  - `select_device(preferred)` accepts indexed CUDA strings
    (`"cuda:0"`, `"cuda:1"`, ...). Unchanged callers (`"auto"`, `None`,
    `"cuda"`, `"cpu"`, `"mps"`) keep working.
  - New `available_cuda_devices() -> list[str]` returns
    `["cuda:0", "cuda:1", ...]` for present GPUs, or `[]`.
  - New `resolve_device(preferred, *, fallback="cuda:0")` —
    operator-facing helper that takes any of the above and returns
    a concrete device, **falling back with a warning** when the
    requested index isn't present (e.g. operator's config says
    `cuda:1` but they're on a single-GPU host).
  - New `tune_cpu_threads(reserved_modules=N)` — sets
    `torch.set_num_threads(max(1, cpu_count // 2))` so multiple
    CPU-bound modules don't trash each other's pool. Called from
    `kaine/cycle/__main__.py` on boot.
  - `describe_host()` gains a `cuda_devices: list[dict]` field with
    per-device name/total_vram_gb/free_vram_gb.
- `kaine/modules/topos/encoder.py` — already takes
  `device_preference`; passes through `resolve_device`. No behavior
  change beyond honoring `cuda:1`.
- `kaine/modules/mnemos/embeddings.py` — same.
- `kaine/modules/audio_in/module.py` — explicitly forward an
  `emotion_device` kwarg through `AudioInput.__init__` so the
  emotion classifier's CPU pin shows up in the startup log instead
  of being implicit.
- `kaine/modules/hypnos/voice_alignment.py` — `VoiceAlignmentConfig`
  gains a `training_device: str = "cuda:0"` field. The trainer
  implementation honors it. (FakeTrainer accepts and records the
  choice for tests.)
- `config/kaine.toml` defaults updated to match paper §6.1:
  - `[topos].device = "cuda:1"`     (was `"auto"`)
  - `[mnemos].device = "cpu"`       (was `"auto"` — MiniLM-L6 is
    tiny; CPU is plenty and it leaves cuda:1 fully available for
    Topos and cuda:0 fully for Lingua/Hypnos)
  - `[hypnos.voice_alignment].training_device = "cuda:0"` (new key)
- `kaine/boot.py`:
  - After registry build, log one line per module:
    `"device assignment: <module> → <device>"`.
  - Forward emotion_device from `[audio_in]` and training_device from
    `[hypnos.voice_alignment]`.
- `kaine/cycle/__main__.py` — calls `tune_cpu_threads()` once at
  boot, before constructing modules.
- `SETUP.md` — §0 GPU allocation table is now authoritative and
  matches the code defaults. §1.4 marked decided.
- `DEPENDENCIES.md` — adds the GPU-assignment comment block for
  external services with explicit CUDA_VISIBLE_DEVICES guidance.
- Tests: `select_device("cuda:1")` returns the string when GPU 1
  exists; `resolve_device("cuda:1")` falls back to `cuda:0` with a
  warning when only one GPU is present; `tune_cpu_threads()` sets the
  torch thread count it claims; boot-time logging emits one line per
  module; module factories thread the new keys correctly.

## Capabilities

### Modified Capabilities

- `hardware` — adds indexed CUDA support, multi-device fallback, CPU
  thread tuning, and per-device introspection.
- `boot` — adds device-assignment logging on registry build.

## Impact

- **No new external deps.** The change is in `kaine/hardware.py`,
  module factories, and a few config defaults.
- **Operators on single-GPU hosts:** their config asking for
  `cuda:1` falls back to `cuda:0` with a warning. No crash.
- **Operators on CPU-only hosts:** every device key falls back to
  `cpu`. No crash.
- After merge, tag `v1.3-multi-gpu`.
