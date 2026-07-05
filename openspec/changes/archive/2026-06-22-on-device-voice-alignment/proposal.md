## Why

The shakedown surfaced that `[hypnos.voice_alignment]` was staged but **disabled**,
and that it cannot simply be turned on. Stage-2 sleep-cycle voice alignment trains
the organ on the entity's own lived outputs (DPO/QLoRA via the out-of-process
Unsloth subprocess bridge, `voice-alignment` / `voice-alignment-training`). But the
trainer and the resident organ server both need the single usable 12 GB GPU (the
4070 SUPER; the 3070 is occupied by Chatterbox). The abliterated 4B organ served by
`llama-server` holds VRAM continuously, and a 4B bf16 LoRA training step needs
≈9.8 GB. They do not fit at the same time, and **nothing unloads the organ for the
training window**. So the one mechanism by which the entity's voice individuates
over sleep is inert — which also starves the individuation signal that
`individuation-instrument-gate` depends on (trained adapters are one of its
secondary identity signals).

A second gap: `[hypnos.voice_alignment].base_model_path` is unset. The trainer needs
**HF safetensors** to load and attach a LoRA; the served organ is a **GGUF**. With
no safetensors path the trainer has nothing to train from. The abliterated 4B
safetensors exist (the KAINE abliteration), but the path was never wired.

The fix is to make the sleep-training window **own the GPU cooperatively**: at the
start of the window unload the resident organ (free its VRAM), run the trainer
against the abliterated safetensors, then reload the organ — applying the new
adapter if training produced one. Sleep is the natural window for this: during
consolidation the entity is not speaking, so the organ's temporary absence is
expected, not a regression. The work must be **real or fail honestly** — the unload
must actually free VRAM and the reload must actually serve, or the cycle reports the
failure and continues; no pretend swap.

This is **design-of-record** for the rebuild. It boots no entity, ships
voice-alignment **disabled** (unchanged), and keeps the existing operator opt-in
(`enabled = true` AND `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`) and the
capability-loss welfare veto intact.

## What Changes

- **Managed organ-server lifecycle for the training window.** The system SHALL be
  able to **unload** the resident organ server (releasing its GPU memory) at the
  start of the voice-alignment training window and **reload** it afterward. The
  reload SHALL apply the newly accepted adapter when training produced one. This
  builds on the existing `hot_swap_mode` (`manual` / `reload_endpoint` /
  `restart_service`) by adding the *unload-before / reload-after* bracket the
  on-device single-GPU case requires.

- **`base_model_path` wired to the abliterated safetensors.** The trainer's
  `base_model_path` SHALL point at the KAINE abliterated Qwen3.5-4B **safetensors**
  (not the served GGUF), so the QLoRA/bf16-LoRA step has real weights to attach to.

- **Organ-absent window is tolerated, not crashed.** While the organ is unloaded,
  organ-dependent cognition (Lingua generation, the A/B-divergence eval arm) SHALL
  degrade gracefully — deferred/skipped for the window — rather than erroring. The
  window falls inside sleep, when the entity is not expected to speak.

- **Cooperate with the GPU pre-boot headroom gate.** Before reloading the organ the
  system SHALL verify the device has headroom (reuse `gpu-preflight`); if the
  trainer left the device short it SHALL report rather than thrash, and SHALL NOT
  terminate foreign processes.

- **Welfare veto and opt-in unchanged.** The capability-loss veto that blocks adapter
  promotion and the two-key operator opt-in remain exactly as specified; this change
  only adds the GPU-window mechanics around them.

## Impact

- Specs: MODIFY `voice-alignment-training` (extend hot-swap to bracket the training
  window with unload/reload; require `base_model_path` wired for on-device);
  ADD a `voice-alignment` requirement for the cooperative single-GPU training window.
- Code (build phase): the organ-server manager (start/stop/reload of `llama-server`
  with the new adapter), the sleep-phase hook that brackets the trainer call with
  unload/reload, Lingua's organ-absent tolerance, and the gpu-preflight check before
  reload. Trainer internals (`kaine/modules/hypnos/subprocess_trainer.py`) are reused
  unchanged.
- Config: set `[hypnos.voice_alignment].base_model_path` (operator config, pointing
  at the local abliterated 4B safetensors); document the on-device unload/reload
  bracket. Shipped config keeps voice-alignment disabled (first-boot guard
  unaffected).
- Non-goals: the abliteration itself (done), publishing the organ (operator), the
  DPO algorithm, or multi-GPU layouts (a host with a second free GPU can serve and
  train concurrently and skips the unload bracket — detect and no-op there).
