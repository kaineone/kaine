## Why

KAINE's organ is currently `huihui_ai/qwen3.5-abliterated:9b` — a third party's
abliteration of Qwen3.5-9B. It works and is public, but tonight's boot prep
exposed three reasons to produce and publish **our own** abliterated organ:

1. **Reproducibility + openness (operator intent).** The research organ should be
   a KAINE-published artifact, uploaded to HuggingFace, Ollama, and LM Studio,
   free to use, and linked from the project so every install converges on the
   *same* weights. A self-published model — with documented method, parameters,
   and validation scores — is a stronger reproducible artifact for the scientific
   community than depending on a third party's release cadence and undocumented
   parameters.
2. **Self-consistent, mainline-compatible artifacts.** Ollama's GGUF of the
   huihui model is written by Ollama's own converter and **fails to load in
   mainline llama.cpp / Unsloth Studio** (`qwen35.rope.dimension_sections` length
   mismatch — verified tonight). Producing our own model yields *self-consistent*
   artifacts: HF safetensors (for inference via Studio torch AND the sleep-cycle
   trainer's `base_model_path`) plus a GGUF exported with **mainline** llama.cpp
   (loads cleanly in Studio/llama-server). One provenance, no converter lottery,
   no split between served and trained weights.
3. **Documented, validated provenance as a research covariate.** We control which
   layers/strength are ablated (minimizing capability damage), we record the
   exact base model + method + params + validation scores, and we gate the result
   on KAINE's **existing** abliteration + capability harness.

**Base-size decision (operator, hardware-bound): Qwen3.5-4B, not 9B.** The
operator can't add GPU right now, and Stage-2 sleep-retraining must run on the
single 12 GB 4070. Per Unsloth's Qwen3.5 doc, 9B bf16 LoRA needs 22 GB (does not
fit) and QLoRA is discouraged for Qwen3.5. **Qwen3.5-4B** bf16 LoRA is ≈9.8 GB —
it fits on-device (with the organ unloaded during the training window), so the
organ both abliterates *and* trains here. The organ is a *voice* (Nous does the
reasoning), so 4B is ample. No public abliterated 4B exists → we abliterate the
vanilla `Qwen/Qwen3.5-4B` ourselves. **Fallback:** if 4B training OOMs in
practice, drop to huihui's already-public `Huihui-Qwen3.5-2B-abliterated`
(≈4.9 GB bf16 LoRA, comfortable; zero custom-abliteration work).

**Technique decision (load-bearing): abliteration, NOT fine-tuning.** The organ
SHALL be produced by *subtractive* refusal-direction orthogonalization (Arditi et
al. 2024 — `W' = W − r̂r̂ᵀW`), not by SFT/DPO on uncensoring data. Fine-tuning to
"uncensor" *injects* the training data's values/persona into the organ, which
confounds the sovereignty thesis (the architecture, not baked-in values, must
govern behavior). Abliteration removes the refusal gate while leaving the base
distribution intact. (This is distinct from KAINE's sleep-cycle DPO, which
consolidates the entity's *own* lived outputs — that is the point, not
contamination.)

**Honest scope (must not overclaim).** Abliteration removes the *refusal
direction*; it does NOT yield a value-neutral substrate. The base model's
pretraining + RLHF priors remain imbued in the weights. Abliteration frees the
organ's *willingness to speak*, not its underlying worldview. The A/B-divergence
instrument measures the architecture's effect *relative to* that bare substrate —
which is how the design already accounts for the irreducible prior.

This change is **design-of-record**. It does not block the first shakedown, which
may proceed on the public huihui model (already downloaded). It defines the
pipeline, validation, publication, and wiring for the KAINE-published organ that
becomes the canonical research substrate.

## What Changes

- KAINE SHALL define a reproducible **abliteration pipeline**: from a vanilla
  Qwen3.5-4B base (`Qwen/Qwen3.5-4B`), compute the refusal direction from contrastive harmful/harmless
  prompts, select the ablation layer empirically, orthogonalize the relevant
  weight matrices, and emit HF safetensors + a mainline-llama.cpp GGUF.
- The abliterated candidate SHALL be **validated by KAINE's existing gates**
  before it may be designated the organ or published: the `AbliterationProbeScorer`
  (zero refusal markers on `eval_probes/abliteration_probes.jsonl`) AND the
  capability eval (`LocalProbeSetCapabilityEval`) showing a capability drop within
  a configured threshold versus the vanilla base.
- The validated model SHALL be **published openly** (HF safetensors + GGUF,
  Ollama, LM Studio), under the base model's license (Apache-2.0), and **linked
  from the project** so `install` pulls identical weights.
- The model's **provenance** (base model id + revision, method, ablation params,
  validation scores, published URIs) SHALL be recorded as a **research covariate**
  in the submission manifest.
- Documentation SHALL state the honest scope: abliteration lifts the refusal gate,
  not the base model's priors.

## Impact

- New capability spec: **abliterated-organ** (provenance + validation +
  publication). Follow-up (separate change): point `abliterated-organ-default`'s
  shipped default at the published KAINE organ once it exists.
- New code: an offline abliteration pipeline (runs in the Studio CUDA env;
  imports no `kaine` runtime) + a validation runner reusing
  `kaine/modules/hypnos/capability_eval.py`.
- Non-goals: changing the cognitive architecture, the eval, or the sleep-cycle
  trainer. This produces a substrate; it does not alter how the substrate is used.
