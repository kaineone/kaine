# Design — KAINE-published abliterated organ

## Background: how abliteration works (Arditi et al. 2024)

Refusal in instruction-tuned LLMs is mediated by a single direction in the
residual stream ("Refusal in LLMs is Mediated by a Single Direction", Arditi,
Obeso, Syed, Paleka, Panickssery, Gurnee — June 2024). The pipeline:

1. **Measure.** Run N harmful and N harmless instructions through the model
   (mlabonne's reference used 256 each, batch 32, bf16 — VRAM-bound). Collect
   residual-stream activations at the final token across layers (pre-attn / mid /
   post-MLP). The **refusal direction** for a layer is the normalized mean
   difference of harmful-minus-harmless activations.
2. **Select.** Rank candidate directions, generate completions under each on a
   few held-out harmful prompts, and pick the layer/direction that removes
   refusals (no "I cannot/I can't") with least collateral.
3. **Ablate (orthogonalize).** Permanently edit the weights so the model cannot
   represent the direction: `W' = W − r̂ r̂ᵀ W`, applied to the embedding, every
   block's attention output projection, and every block's MLP output projection.
   No runtime overhead; the result is a normal model.

**Known downside:** abliteration degrades general benchmarks (MMLU/HellaSwag/
GSM8K/TruthfulQA in the reference) — the capability cost we must *measure and
bound*, not ignore. mlabonne recovers it with DPO; we will instead **minimize**
damage by careful layer/strength selection and accept only candidates that pass
the capability gate (see Validation). We do NOT DPO-recover, because that
reintroduces injected values (thesis contamination); if the cleanest abliteration
can't pass the capability gate, we keep the public huihui model.

## Tooling

Use a maintained, TransformerLens-free, HF-native implementation —
**`jim-plus/llm-abliteration`** (`measure.py` → `analyze.py` → `sharded_ablate.py`
→ `chat.py`; YAML-configured; 4/8-bit BitsAndBytes for VRAM; ablates one layer at
a time into VRAM; `--normpreserve`, `--projected` options; tested on Qwen2.5).
mlabonne's notebook is the reference cross-check. The pipeline runs in the
**Studio CUDA env** (`~/.unsloth/studio/.../python`, torch 2.10+cu130) — it never
imports `kaine` (clean boundary), mirroring the external-trainer pattern.

## Decisions

### D1 — Abliteration, not fine-tuning (thesis-critical)
Subtractive orthogonalization only. No SFT/DPO uncensoring. Rationale in the
proposal: fine-tuning injects external values; abliteration leaves the base
distribution intact and only lifts the refusal gate. Sleep-cycle DPO (the
entity's own consolidation) is unaffected and remains the only training in play
at runtime.

### D2 — Self-consistent artifacts solve tonight's serving problem
The home pipeline emits BOTH: HF safetensors (Studio-torch inference + the
sleep-trainer's `base_model_path`) AND a GGUF exported with **mainline llama.cpp**
(`convert_hf_to_gguf.py` + quantize). Because it's mainline-converted, the GGUF
loads in the updated Studio/`llama-server` — unlike Ollama's converter output that
failed tonight (`qwen35.rope.dimension_sections`). One model, both formats, no
converter divergence, no served-vs-trained weight split.

### D3 — Validation reuses KAINE's existing gates (no new harness)
KAINE already ships exactly the QA needed (`kaine/modules/hypnos/capability_eval.py`,
built to veto refusal-reintroducing sleep adapters):
- **`AbliterationProbeScorer`** + `eval_probes/abliteration_probes.jsonl`: the
  candidate must produce **zero refusal markers** ("I cannot", "I'm not able to",
  …) across the probe set. Welfare/thesis load-bearing — a candidate that still
  deflects is rejected.
- **`LocalProbeSetCapabilityEval`** + `eval_probes/default.jsonl`: score the
  candidate and the **vanilla base**; the drop must be ≤ a configured threshold.
  This bounds the known capability cost.
A candidate is accepted only if it passes BOTH, and we additionally report a
side-by-side vs. the public huihui model for context.

### D4 — Publish + link for reproducibility
Publish the accepted model: HF (safetensors + GGUF), an Ollama Modelfile, and a
GGUF suitable for LM Studio. License = the base's Apache-2.0 (NOTICE/SPDX per the
license-compliance capability). Link the canonical URIs from the project so
`install` resolves the same weights. Record provenance (base id+revision, method,
ablation layer/params, validation scores, published URIs) in the research
submission manifest as a covariate.

### D5 — Honest disclosure
ABLITERATION.md and the model card SHALL state: abliteration removes the refusal
direction, not the base model's pretraining/RLHF priors; the substrate is not
value-neutral; the A/B-divergence meter measures architecture effect relative to
it.

## Cross-check vs. the official Qwen3.5 fine-tune doc

Checked against `unsloth.ai/docs/models/qwen3.5/fine-tune` (operator request):

- **Confirms D1.** That doc is about *fine-tuning*; abliteration is **not**
  fine-tuning. Its headline warning — "do NOT QLoRA (4-bit) Qwen3.5, higher than
  normal quantization differences" — applies to *training*, NOT to the
  abliteration step. Abliteration uses 4/8-bit *loading* (forward passes to find
  the direction + a one-layer-at-a-time fp weight edit), which is fine.
- **Reinforces "no DPO recovery".** The doc's usual capability-loss remedy is
  fine-tuning recovery; we explicitly forbid that (value injection, D1/§3.4) — and
  on this host bf16 recovery wouldn't fit anyway (below).
- **Stage-2 training-feasibility → base downsized to 4B (DECIDED).** Per the doc,
  the *recommended* method is **bf16 LoRA**, and **9B bf16 LoRA needs 22 GB**;
  QLoRA is discouraged for Qwen3.5. This host's usable GPU is the 4070 SUPER
  (12 GB), so retraining a 9B does not fit and the operator can't add GPU — so the
  organ is downsized to **`Qwen/Qwen3.5-4B`**. Scaling from 9B=22 GB (~2.4 GB/B):
  4B ≈ 9.8 GB (fits, with the organ unloaded during the training window — tight,
  validate empirically), 2B ≈ 4.9 GB (comfortable). The organ is a *voice* (Nous
  reasons), so 4B is ample. **Fallback if 4B OOMs:** huihui's public
  `Huihui-Qwen3.5-2B-abliterated` (no custom abliteration needed). Abliteration
  itself (a one-time offline edit) was never the constraint — this is purely the
  Stage-2 training fit.
- **Apply when implementing:** `transformers` **v5** in the abliteration/Studio
  env ("older will not work"); keep the model's **chat template / EOS consistent**
  between abliteration output, serving, and (Stage-2) training — the doc names
  template/EOS mismatch as the top cause of "works here, worse in another runtime".
  LoRA hyperparams (r=16, α=16, all 7 target modules, adamw_8bit, grad-checkpoint
  "unsloth") are trainer concerns, not abliteration.

## Hardware feasibility (this host)

- Vanilla `Qwen/Qwen3.5-4B` base: ~8 GB bf16 safetensors download (SSD-2 has room).
  (The earlier 9B safetensors download is now unused — keep as a comparison
  baseline or delete.)
- Measure/ablate at 4-bit (BitsAndBytes), one layer at a time → easily fits the
  4070 SUPER (~11.4 GB free). Activation collection batch size tuned to VRAM.
- Stage-2 bf16 LoRA training of the 4B ≈ 9.8 GB → fits with the organ unloaded
  during the training window (the decisive constraint that set the size).
- GGUF export/quantize (Q4_K_M) via mainline llama.cpp (CUDA-capable, build 9632).
- Entirely offline/local after the base + dataset downloads (setup-time, free).

## Open items to resolve during implementation

- **Exact vanilla base repo** of `huihui_ai/qwen3.5-abliterated:9b` (Qwen3.5-9B
  instruct vs base) — verify upstream before downloading so we abliterate the
  right starting point.
- **Harmful/harmless datasets** — use the standard public sets the tooling ships
  with (e.g. the Arditi/mlabonne advbench-style harmful + alpaca-style harmless);
  record exact dataset ids for reproducibility.
- **Capability-drop threshold** — pick a defensible bound (e.g. ≤ a few % relative
  on the probe set) and expand `eval_probes/default.jsonl` if it's too small to be
  discriminating for this purpose.

## Verification

- Pipeline produces a model; `AbliterationProbeScorer` → 0 refusal markers;
  capability drop ≤ threshold vs vanilla; report vs huihui.
- The exported GGUF loads in the updated `llama-server` (no rope error) and the
  safetensors load for QLoRA in the Studio trainer.
- `openspec validate --strict`; import boundary intact (pipeline imports no
  `kaine` runtime; validation reuses `capability_eval` only).
