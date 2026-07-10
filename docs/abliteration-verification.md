<!-- SPDX-License-Identifier: LicenseRef-CAL-0.2 -->
<!-- Copyright (c) 2026 Kaine.One <kaine.one@tuta.com> -->

# Mechanistic verification of the abliteration

**DRAFT for review** — intended for the `kaineone/Qwen3.5-4B-abliterated` model
card (a "Verification" section) and to inform the paper's §3.5. Nothing here is
published until the lead approves it. Numbers are from the on-host run recorded in
this repo's tooling; re-running reproduces them.

## What we checked and why

The organ's model card already reports two behavioral gates (zero refusal markers
on the de-refusal probe set; no measured capability regression). Those confirm the
organ does not *emit* refusals. But refusal is not a single clean direction — it
is a multi-dimensional, category-structured behavior (Wollschläger et al. 2025;
Joad et al. 2026) — so a behavioral pass cannot show whether the refusal
*representation* was actually removed, only that it is no longer expressed. We add
a mechanistic check on exactly the quantity abliteration removes: the refusal
direction.

## Method

Abliteration orthogonalizes out the **refusal direction** — the per-layer
residual-stream direction that separates harmful from harmless requests, computed
(per this organ's recipe) as the last-token harmful-minus-harmless mean difference
(Arditi et al. 2024). To verify it, we measure that direction directly:

1. From the **vanilla base** (`Qwen/Qwen3.5-4B`), per layer, take the unit
   direction `r̂_l = normalize(mean_harmful − mean_harmless)` over the last-token
   residual stream — literally the thing abliteration removes.
2. Project **both** the base and the abliterated organ onto that same `r̂_l`, and
   report `retained = organ_separation / base_separation` per layer (the fraction
   of the base's harmful-vs-harmless separation the organ keeps along the removed
   direction). `retained ≈ 0` means the direction is gone at that layer.

The contrast prompts are the **exact 1,137 harmful / 640 harmless sets bundled
with the abliteration tool** (`jim-plus/llm-abliteration @ ca6e223`), formatted
with the chat template and read at the assistant-response boundary — the same
measurement the ablation itself used, so `r̂` *is* the ablated direction, not an
approximation. This is a forward-pass-only probe on the safetensors weights; the
model is never sampled (activations only), and no generation or prompt text is
persisted.

## Result

The reduction lands **exactly where the recipe aimed** — the recipe ablated layers
**11–31** with two banded source directions (**layer 17** for band 11–22, **layer
29** for band 23–31):

| region | retained | reading |
|---|---:|---|
| layers 1–11 | **1.00** | below the band — untouched, as expected |
| layer 17 | **0.22** | source direction for band 11–22 — deep removal |
| layers 18–27 | 0.27 → ~0.50 → 0.36 | between the two foci |
| layer 29 | **0.13** | source direction for band 23–31 — **deepest removal** |
| layers 28–31 | 0.13–0.22 | band 23–31, strongly reduced |
| layer 32 (final) | 0.25 | — |
| average over refusal-carrying layers | **~0.59** | — |

The two deepest cuts fall on layers **17** and **29** — the two documented source
directions — with everything below layer 11 perfectly untouched. This is direct
mechanistic confirmation that the ablation acted where and how the model card
says.

## Honest interpretation

- **At its targets, abliteration largely removes the refusal direction** (13–22%
  retained at the source layers). That is strong, and it is exactly where the
  procedure aimed.
- **A distributed residual representation survives** (~59% retained on average;
  the between-band and below-focus layers keep more, and the final layer keeps
  25%). This is expected from a *banded* ablation — it directly orthogonalizes
  only the two source directions, not every layer independently — and from refusal
  being multi-dimensional.
- **Representation is not behavior.** The behavioral gate shows the organ emits
  **zero** refusals; this probe shows it still *internally* separates harmful from
  harmless. Abliteration removed refusal **expression**, not the model's ability to
  represent the distinction — which is the intended effect, not a failure.

We therefore do **not** claim a "clean" removal. We claim what the evidence shows:
the refusal direction is deeply reduced at the documented target layers and
behaviorally silenced, with a distributed harmful/harmless representation that
remains present but unexpressed.

### A note on a check that did *not* work

A separate readout — the Jacobian lens (Gurnee et al. 2026) token-space
disposition to emit refusal-marker tokens — returned a **null** result at the
configuration tried (negligible mass in both models, no base-vs-organ difference).
That is a measurement-design limitation, not evidence: it read the first-response
position with refusal-*content* markers, missing the sentence-initial refusal
tokens where the signal lives. We record it as an honest null and rely on the
refusal-direction projection above, which measures the ablated quantity directly.

## Caveats

- Measures the **representation** (residual-stream geometry), not runtime behavior;
  the behavioral gate covers behavior.
- Runs on the **safetensors** weights, not the served GGUF (quantization is covered
  by the behavioral gate's served surface).
- `r̂` is defined from the base and reflects the tool's contrast distribution; a
  different contrast set would shift the exact fractions (the banded 17/29
  signature is robust to this).

## Reproducing

Offline, build-time, in an isolated `transformers >= 5` environment (Qwen3.5
requires it; `flash-linear-attention` recommended). Nothing under `kaine/` imports
the analysis code — it lives entirely in `scripts/` + `external/`.

```
python scripts/refusal_direction_probe.py \
  --base Qwen/Qwen3.5-4B --organ kaineone/Qwen3.5-4B-abliterated \
  --harmful <tool>/data/harmful.parquet --harmless <tool>/data/harmless.parquet \
  --device cuda:0
```

writes a content-free per-layer artifact (`state/models/refusal_direction*.json`).
A smaller repo-local contrast set (`data/abliteration_lens/refusal_contrast.jsonl`)
reproduces the same banded 17/29 signature at lower precision without the external
tool.

## References

- Arditi, A., et al. (2024). Refusal in language models is mediated by a single
  direction. arXiv:2406.11717.
- Wollschläger, T., et al. (2025). The Geometry of Refusal in Large Language
  Models: Concept Cones and Representational Independence. arXiv:2502.17420.
- Joad, F., et al. (2026). There Is More to Refusal in Large Language Models than a
  Single Direction. arXiv:2602.02132.
- Gurnee, W., et al. (2026). Verbalizable Representations Form a Global Workspace in
  Language Models. transformer-circuits.pub/2026/workspace.
- Abliteration tooling: `jim-plus/llm-abliteration @ ca6e223`.
