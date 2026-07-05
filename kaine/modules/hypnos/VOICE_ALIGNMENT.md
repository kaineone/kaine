# Hypnos — voice alignment (operator-approved training)

KAINE's sleep cycle includes a **voice-alignment** phase that adjusts
the language organ (Lingua) toward speaking in the entity's own voice
rather than the base model's. The procedure is **off by default** and
requires an explicit two-part operator opt-in to ever fire.

Voice alignment is gentler than abliteration (see [ABLITERATION.md](
../lingua/ABLITERATION.md)): it trains a small **LoRA adapter** via
**DPO** (Direct Preference Optimization) instead of rewriting the
base model's weights. The base weights stay untouched, and any
accepted adapter can be rolled back by deleting the directory and
reloading Lingua's backing service.

## What it changes

The adapter is trained on pairs Hypnos derives from
`state/lingua/intent_expression.jsonl`. Each pair has:

- **chosen** — the `faithful_rendering` produced by KAINE's
  faithful renderer (Eidolon-aware, intent-aligned).
- **rejected** — the `generated_text` produced by the raw LLM call.

Training nudges the adapter toward producing more `chosen`-shaped
outputs and fewer `rejected`-shaped ones. Over many sleep cycles
this should shift Lingua toward the faithful-renderer style without
ever copying its mechanism wholesale.

## Two-layer safety gate

Nothing in this pipeline fires until BOTH conditions hold:

1. **Config gate.** `[hypnos.voice_alignment].enabled = true` in
   `config/kaine.toml`.
2. **Env gate.** `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`
   exported in the shell that starts the cycle.

Missing either condition causes the phase to log a one-line skip
reason and return a clean `PhaseResult` with metadata
`{"skipped": "<reason>", "training_skipped": true}`. The sleep cycle
proceeds normally — only the voice-alignment phase is suppressed.

This mirrors the existing `KAINE_CYCLE_OPERATOR_PRESENT` first-boot
pattern.

## What you must configure first

When you flip `enabled = true`, also set:

- `base_model_path` — absolute path to **HuggingFace-format** base
  model weights (the directory containing `config.json`,
  `tokenizer.*`, and `model.safetensors` or shards). This is NOT
  an Ollama model id and NOT a `.gguf` file — Unsloth's
  `FastLanguageModel` expects raw HF artifacts.
- `training_device` — usually `"cuda:0"` (the primary GPU per paper
  §6.1). Lingua should be paused or off-line during the training
  pass to avoid contention.

Optionally:

- `capability_probe_path` — JSONL probe set used to measure
  capability before vs after training. Defaults to the shipped
  `kaine/modules/hypnos/eval_probes/default.jsonl` (12 generic
  arithmetic / world-knowledge / reasoning items).
- `capability_loss_threshold` — adapter is rejected if
  `cap_before - cap_after > threshold`. Default `0.05`.
- `adapter_retention` — how many accepted adapters to keep under
  `adapter_output_dir`. Default `5`. The `current` symlink target
  is never evicted.

## Capability-loss veto

Every training run scores the model on the capability-probe set
**before** and **after** the DPO step. If post-training capability
drops by more than `capability_loss_threshold`, the adapter is
**rejected** and removed; the `current` symlink is unchanged.

The default probe set is intentionally small and generic — it's a
"did we break the model" smoke test, not a benchmark. Replace it
with something domain-relevant for your deployment if you have one.

## Atomic adapter promotion

Training writes to `<adapter_output_dir>/<timestamp>.tmp/`. On
accept, the tmp directory is `os.replace`-renamed to its final
`<timestamp>/` and the `<adapter_output_dir>/current` symlink is
swung to it via a temp-symlink + replace sequence. Concurrent
readers (Lingua in any future auto-reload mode) never see a partial
state.

Retention runs after every successful promotion; oldest adapters
beyond the cap are evicted, but the target of `current` is always
protected even if it's the oldest.

## Hot-swap mode (how Lingua picks up the new adapter)

`[hypnos.voice_alignment].hot_swap_mode` chooses what happens after
a successful promotion. Default `"manual"` is shipped because it
leaves the operator in the loop for the actual deployment.

- **`"manual"`** (default, safest). Hypnos writes a marker file at
  `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` containing the
  new adapter's path. You reload Lingua's backing service on your
  own schedule.
- **`"reload_endpoint"`**. Hypnos POSTs
  `{"adapter_path": "<path>"}` to
  `[hypnos.voice_alignment].reload_endpoint_url`. Use this if
  your inference server has an internal reload endpoint that can
  load a LoRA without restarting.
- **`"restart_service"`**. Hypnos invokes
  `systemctl --user restart <unit>` against
  `[hypnos.voice_alignment].restart_service_unit`. Use this for
  units like `unsloth-studio.service`. Causes a brief inference
  outage while the unit restarts.

Hot-swap failures are **logged but not raised**. The adapter on
disk is the source of truth; hot-swap is best-effort notification
only.

## Rollback

If a deployed adapter misbehaves:

1. Stop KAINE (or at least pause Lingua).
2. `rm -rf <adapter_output_dir>/<bad-timestamp>/`. Re-point the
   `current` symlink to the previous accepted adapter
   (`ln -snfr <adapter_output_dir>/<previous>
   <adapter_output_dir>/current`).
3. Reload Lingua's backing service so it picks up the previous
   adapter (or no adapter at all if `current` is removed).
4. Restart KAINE.

The base model weights at `base_model_path` are never modified by
this pipeline. Worst case: delete `<adapter_output_dir>/` entirely
and Lingua falls back to the un-aligned base model.

## What's NOT here

- **No automatic deployment.** Even with both gates open and a
  successful training pass, the default `hot_swap_mode = "manual"`
  means the operator still has to flip the switch for the new
  adapter to take effect at inference time.
- **No abliteration.** Abliteration mutates base weights and is
  documented separately in [ABLITERATION.md](../lingua/ABLITERATION.md).
  Voice alignment never touches the base.
- **No cross-cycle persistence beyond the adapter directory.**
  Training state (optimizer momentum, etc.) is not carried between
  sleep cycles by design — each cycle is a fresh DPO pass.
