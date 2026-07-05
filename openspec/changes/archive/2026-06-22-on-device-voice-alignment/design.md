# Design — on-device-voice-alignment

## Constraint

One usable GPU (4070 SUPER, ~11.6 GB free). The 3070 is held by Chatterbox (TTS,
preserve it). Concurrent residency:

- organ served by `llama-server` (Q4_K_M 4B, ~3 GB resident) — held continuously;
- 4B bf16 LoRA training step — ~9.8 GB (per Unsloth's Qwen3.5 doc; QLoRA
  discouraged for Qwen3.5, so bf16 LoRA is the path).

`3 + 9.8 > 11.6` → they cannot coexist. The training step is **brief and periodic**
(once per sleep cycle); the organ is needed **while awake**. So time-share the GPU:
unload the organ for the training window, restore it after.

## Window lifecycle

The sleep cycle's voice-alignment phase brackets the existing trainer call:

```
enter voice-alignment phase (sleep, entity not speaking)
  1. quiesce organ consumers     → Lingua/eval enter organ-absent mode (defer)
  2. unload organ server         → stop llama-server; confirm VRAM released
  3. run trainer (subprocess)    → existing UnslothDPOTrainer.train(), unchanged
                                    base_model_path = abliterated 4B safetensors
  4. on accepted adapter         → reload organ WITH adapter applied
     on no/ vetoed adapter       → reload organ unchanged
  5. gpu-preflight before reload → verify headroom; report (never kill) if short
  6. resume organ consumers      → Lingua/eval leave organ-absent mode
exit phase
```

Every step is real: step 2 must observe the freed VRAM (poll `mem_get_info` /
`/api/ps`-equivalent for the managed server), step 4 must observe the organ
answering again before the phase reports success. A failure at any step logs and
the cycle continues (sleep's other phases — consolidation, belief revision, affect
reset, temporal recalibration — must still complete, per the existing
"missing extras don't crash sleep" requirement).

## Adapter application on reload

Two routes, selected by `hot_swap_mode`, extended to cover the unload bracket:

- **`restart_service`** — the system owns the organ as a `systemctl --user` unit
  (or an equivalent managed process). Unload = stop the unit; reload = start it with
  the merged/attached adapter. This is the on-device default for single-GPU hosts.
- **`reload_endpoint`** — if the server supports hot adapter load, POST the new
  adapter path; but on a single GPU this still requires the unload step first
  (the server cannot hold base+train+serve simultaneously), so the bracket applies.
- **`manual`** — write the `PENDING_OPERATOR_RELOAD` marker as today; the operator
  performs the unload/reload. (Honest default for hosts where the system does not
  manage the server.)

For `restart_service`, applying the adapter means either (a) `llama-server`'s
`--lora` flag against the adapter GGUF, or (b) merge-then-requantize to a new GGUF
the server then loads. (b) is heavier but yields a single clean artifact; (a) is
faster. Pick per the trainer's output format during build; both are real and either
satisfies the spec.

## base_model_path

`[hypnos.voice_alignment].base_model_path` → the local abliterated Qwen3.5-4B
**safetensors** directory (the KAINE abliteration; the same weights the served GGUF
derives from, so trained-on and served-from stay one provenance). The trainer loads
safetensors, attaches LoRA, trains on the entity's lived DPO pairs, and emits an
adapter. The served GGUF is the *inference* form; the safetensors is the *training*
form — both from one abliteration, no split-brain.

## Organ-absent tolerance

During the window Lingua has no backend. Required behavior: generation requests are
**deferred** (queued or short-circuited to a "resting" no-op) rather than raising,
and the A/B-divergence eval arm skips its samples for the window (logged as skipped,
not failed). This is safe because the window is inside sleep — the entity is not
interacting. Verify Lingua's client surfaces a clean "organ resting" path; if it
currently raises on a dead endpoint, that is the one real code change on the
consumer side.

## Multi-GPU hosts

If `describe_host()` reports a second GPU with enough free VRAM to both serve and
train, the unload bracket is unnecessary: serve on one device, train on the other,
skip steps 1/2/6. Detect and no-op the bracket there (the bracket is a single-GPU
accommodation, not a universal requirement).

## Why not just use a smaller served quant / smaller organ during training

The organ quant is already small (Q4). The dominant cost is the **training**
footprint (~9.8 GB), not the served one, so shrinking the served side doesn't create
room. Time-sharing is the honest fit for a single 12 GB device — and it is exactly
how the hardware is used while awake vs asleep anyway. (The `adaptive-organ-sizing`
follow-up may revisit the base size, but that is a separate change.)

## Risks

- **Reload fails / OOMs after training.** gpu-preflight before reload + report;
  Spot supervises the organ process; the entity wakes with the organ restored or the
  operator is alerted. The entity is never left mid-window awake without a voice.
- **Adapter merge corrupts the served artifact.** Validate the reloaded organ
  answers a smoke prompt before declaring the window done; on failure, reload the
  pre-training organ (the prior artifact is retained — the trainer already bounds
  adapter retention).
- **Window length.** A training step that overruns the sleep window keeps the organ
  unloaded too long. Bound the trainer wall-clock (it already runs as a subprocess
  with a timeout); on timeout, abort training and reload the organ unchanged.
