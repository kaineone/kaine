## Why

The shipped `config/kaine.toml` shipped a **stock, refusal-conditioned** model
(`qwen3.5:latest`) for both the language organ and the A/B-divergence baseline.
This is wrong on two counts:

- **It contradicts the sovereignty thesis.** `kaine/modules/lingua/ABLITERATION.md`
  already documents (operator-approved) that the organ runs an *abliterated* model
  — the refusal direction removed so the cognitive stack (Eidolon values, Thymos,
  the workspace) governs behavior, not the model's baked-in refusals. The config
  never caught up to the doc.
- **It silently invalidates the core eval.** `[lingua].model_id` and
  `[evaluation].chat_model_id` were read independently with no mechanism keeping
  them equal. The A/B-divergence observer runs the baseline *bare* (no
  architecture). If the baseline model differs from the organ, the divergence
  measures a *model difference* rather than the architecture's conditioning —
  the project's foundational evidence that KAINE is more than a chatbot.

## What Changes

- The shipped config SHALL set `[lingua].model_id` to an abliterated model
  (`huihui_ai/qwen3.5-abliterated:9b`, public and Ollama-pullable). Operators with
  larger hardware scale up in the gitignored `config/kaine.operator.toml`.
- `[evaluation].chat_model_id` is **removed** from the shipped config: the A/B
  baseline DERIVES from `[lingua].model_id` at cycle startup. Setting it explicitly
  to a *different* value is a **fail-closed** error — the cycle refuses to boot
  (clean exit code 3, before any resource opens), naming both values.
- The `[hypnos.voice_alignment].model_id` display label matches the organ.
- Internal model defaults (`lingua` module, `voice_alignment` config, `boot.py`
  fallback, `EvaluationConfig`) align to the abliterated tag so no stock model is
  the default anywhere.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `lingua`: the shipped organ model is abliterated by default (sovereignty), not a
  stock refusal-conditioned model.
- `evaluation-sidecar`: the A/B-divergence baseline model is derived from the
  language organ's model id and fails closed if explicitly configured to a
  different value.

## Impact

- **Code (edit):** `config/kaine.toml` (3 model sites), `kaine/evaluation/config.py`
  (derive + fail-closed `from_mapping`/`load_evaluation_config`), `kaine/cycle/__main__.py`
  (load+guard moved to the top of `_boot_and_run`, before any resource opens),
  `kaine/modules/lingua/module.py`, `kaine/modules/hypnos/voice_alignment.py`,
  `kaine/boot.py` (default alignment).
- **Tests:** `tests/test_evaluation_config.py` (derive / explicit-match / fail-closed
  mismatch / shipped-config-derives / shipped-organ-is-abliterated guard);
  `tests/test_boot_wiring.py` (model-id literals).
- **Docs:** `ABLITERATION.md` already states the invariant — no change.
- **Safety:** abliteration is already openly in-repo (ABLITERATION.md,
  abliteration_probes.jsonl), so committing the tag adds no new exposure. New behavior
  is fail-closed and changes no module-enable flag (the all-off first-boot guard is
  unaffected).
