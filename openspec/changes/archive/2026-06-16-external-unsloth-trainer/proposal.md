# Out-of-process voice-alignment trainer (external unsloth env)

## Why

The Hypnos sleep-cycle voice-alignment phase trains a QLoRA/DPO adapter with
unsloth. The current `UnslothDPOTrainer` imports unsloth **in-process**, in the
entity-runtime venv — which forces the trainer's heavy stack (unsloth, trl,
peft, a specific torch+CUDA) to live in the same interpreter as the live cycle.

On the reference host that is impossible: the runtime venv is Python 3.12 /
torch 2.11+cu128, while the operator's standardized **Unsloth Studio** is a
self-contained Python 3.13 / torch 2.10+cu130 environment. The two cannot share
site-packages (different Python ABI) and installing Studio's unsloth into the
runtime venv would force-downgrade torch and cascade-break jax / torchaudio /
funasr. So the in-process trainer is a dead end here, and today voice-alignment
either stays disabled (the consolidation-divergence signal never fires) or — if
enabled without the extra — fails closed at boot (correctly, but unusably).

More generally the trainer stack is host-specific: per unsloth's docs, AMD GPUs
need unsloth-core while other GPUs can use Studio. The trainer must therefore be
decoupled from the runtime interpreter.

## What Changes

- Add an **out-of-process trainer backend** for the voice-alignment phase: at
  each consolidation, Hypnos writes a job spec (the DPO preference pairs +
  base-model reference + LoRA/DPO hyper-parameters) and invokes a **configured
  external Python interpreter** as an isolated subprocess to run the real
  unsloth DPO, then reads back the produced adapter.
- The trainer interpreter is **configurable** (`[hypnos.voice_alignment]
  trainer_backend` + `trainer_python` + `trainer_workdir`), defaulting to
  in-process for backwards compatibility. On the reference host it points at the
  Unsloth Studio interpreter; an AMD host points it at an unsloth-core env — the
  bridge itself is env-agnostic and version-decoupled (it shells out, so the
  Studio/unsloth version can be updated independently).
- A standalone training entry script runs **inside** the external env. It
  imports only unsloth/trl/peft/datasets (never `kaine`), so it adds no coupling
  to the runtime and respects the sidecar/import boundary.
- **Fail loud, never fake.** A missing/incompatible trainer env, a non-zero
  subprocess exit, or a missing/empty adapter output is a hard error surfaced to
  Hypnos — there is no silent fallback to a no-op "success". The existing
  capability and abliteration gates run unchanged on the returned adapter.

## Impact

- New: a kaine-side subprocess trainer (`kaine/modules/hypnos/`) + a standalone
  external entry script + `[hypnos.voice_alignment]` config keys
  (`trainer_backend`, `trainer_python`, `trainer_workdir`), all shipped so the
  in-process default is unchanged. No runtime dependency added to the entity
  venv (the heavy stack stays in the external env).
- Unblocks the real sleep-cycle voice adaptation — and therefore the
  consolidation-divergence signal — on hosts where the trainer stack is
  incompatible with the runtime venv (the reference host, and AMD hosts).
- The boundary holds: the external entry script does not import `kaine`; the
  in-process path is retained for hosts whose runtime venv can host unsloth.
