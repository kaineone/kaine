# Hardware-aware sleep-trainer provisioning

## Why

The sleep-cycle voice-alignment trainer runs unsloth out-of-process in a
configured external interpreter (`[hypnos.voice_alignment].trainer_python`, see
the `external-unsloth-trainer` change). Which unsloth a host needs is
**hardware-dependent**: per unsloth's documentation, AMD GPUs require
**unsloth-core**, while NVIDIA (and other CUDA) hosts can use **Unsloth Studio**.
Today nothing helps an operator pick or locate the right one — they must know
the matrix and hand-set `trainer_python`. A researcher on AMD who follows the
NVIDIA path (or vice-versa) gets a trainer env that cannot run, discovered only
at the first sleep cycle.

The wizard already detects external service dependencies (Redis, Ollama, Qdrant,
Speaches, Chatterbox) and `kaine.hardware.describe_host()` already reports the
GPU `backend` (`"cuda"` = NVIDIA / `"rocm"` = AMD / `xpu`/`mps`/`cpu`). The
trainer is the one remaining dependency whose provisioning is hardware-specific
and unguided.

## What Changes

- Add **hardware-aware trainer provisioning** to the setup flow: read
  `describe_host()["backend"]` and surface the correct guidance —
  - `cuda` (NVIDIA): Unsloth Studio (a self-contained external env);
  - `rocm` (AMD): unsloth-core in a separate env;
  - `xpu`/`mps`/`cpu`: no GPU trainer — sleep-cycle voice-alignment training is
    unavailable on this host (the phase stays off; the consolidation-divergence
    metric still emits without training).
- **Detect-and-guide, never pretend-install.** The trainer env is a heavy,
  multi-GB external environment, so this is guidance + a real detection probe
  (does the configured/known interpreter exist and can it `import unsloth`?),
  not an auto-install that would lie about what it did. When a usable trainer
  interpreter is found, offer to record its path as
  `[hypnos.voice_alignment].trainer_python` in the operator config.
- Surface it as a **Stage-2 / optional** item — it is only needed when
  voice-alignment training will be enabled, not for a first boot.

## Impact

- `kaine/setup/` gains a hardware-aware trainer-provisioning helper (vendor →
  guidance + a real interpreter probe) and a wizard step; `docs/` gains the
  vendor matrix. No runtime/entity-code change, no new entity-venv dependency
  (the trainer stack stays in its external env). Reuses
  `describe_host()["backend"]` and the existing detect/guide dependency pattern.
- An AMD or NVIDIA researcher is guided to the unsloth their hardware actually
  supports and the trainer path is set for them — the failure mode (a trainer
  env that can't run, found only at first sleep) is caught at setup instead.
