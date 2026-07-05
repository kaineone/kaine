# Tasks — KAINE-published abliterated organ

> Design-of-record. Does NOT block the first shakedown (that may run on the public
> huihui model already downloaded). Build this when the operator gives the go;
> the published model then becomes the canonical research organ via a follow-up
> wiring change to `abliterated-organ-default`.

## 1. Decide + acquire (research mostly done — see design.md)

- [x] 1.1 Confirm the technique: **abliteration (orthogonalization), not
      fine-tuning** (D1). Recorded in `kaine/modules/lingua/ABLITERATION.md`.
- [x] 1.2 Base = **`Qwen/Qwen3.5-4B`**, the official chat model (not `-Base`).
- [x] 1.3 Download `Qwen/Qwen3.5-4B` to the abliteration tooling environment.
- [x] 1.4 Select public harmful/harmless datasets the tooling ships with; pinned
      (the published model card records 1,139 contrastive prompts from
      `jim-plus/llm-abliteration`'s bundled sets).

## 2. Abliteration pipeline (offline, Studio CUDA env, imports no `kaine`)

- [x] 2.1 Vendored `jim-plus/llm-abliteration` at commit `ca6e223` (recorded in
      the published model card).
- [x] 2.2 `measure.py`: collected harmful/harmless residual activations
      (8-bit) → per-layer refusal directions.
- [x] 2.3 `analyze.py`: selected ablation layers 11–31, with layer 17 supplying
      the source direction for 11–22 and layer 29 for 23–31.
- [x] 2.4 `sharded_ablate.py`: norm-preserving orthogonalization of the
      attention-output and MLP-down-projection weights (`scale = 1.0`); emitted
      HF safetensors.

## 3. Validate with KAINE's existing gates (no new harness — D3)

- [x] 3.1 Ran `AbliterationProbeScorer` against
      `eval_probes/abliteration_probes.jsonl` — zero refusal markers (recorded
      in the published model card's Validation section).
- [x] 3.2 Ran `LocalProbeSetCapabilityEval` on the candidate vs. the vanilla
      base — no measured regression (recorded in the model card; the card
      flags these as compact gates, not a comprehensive benchmark).
- [x] 3.3 Side-by-side context vs. the public huihui model recorded in project
      history (`kaine/modules/lingua/ABLITERATION.md` git history; superseded
      by the published KAINE organ as the shipped default).
- [x] 3.4 The published candidate passed both gates; no DPO-recovery was used.

## 4. Export + serve-compat

- [x] 4.1 Exported GGUF via **mainline** llama.cpp (`convert_hf_to_gguf.py` →
      quantize Q4_K_M) — confirmed in the published GGUF repo's provenance note.
- [x] 4.2 GGUF loads in `llama-server`/Studio (no
      `qwen35.rope.dimension_sections` error); safetensors load for QLoRA
      (`[hypnos.voice_alignment].base_model_path` in `config/kaine.toml`).

## 5. Publish + link (D4)

- [x] 5.1 Published HF (safetensors + GGUF) under Apache-2.0; model cards
      include the honest-scope disclosure (D5), validation scores, and
      method/params — verified live at `kaineone/Qwen3.5-4B-abliterated` and
      `kaineone/Qwen3.5-4B-abliterated-GGUF`.
- [x] 5.2 Published an Ollama `Modelfile` alongside the GGUF (LM Studio indexes
      HF GGUF repos directly; no separate publish step needed).
- [x] 5.3 SPDX/NOTICE present in the safetensors repo (`NOTICE` file, Apache-2.0
      attribution to `Qwen/Qwen3.5-4B`).
- [x] 5.4 Canonical URIs linked from `config/kaine.toml`, `docs/tech-choices.md`,
      `docs/hardware.md`, `docs/licenses.md`, and `docs/modules/lingua.md`; the
      install-time downloader records the resolved repo revision as a
      run-manifest covariate (`docs/tech-choices.md`).

## 6. Docs + validate

- [x] 6.1 `kaine/modules/lingua/ABLITERATION.md` rewritten: method, params,
      validation, and the honest-scope note (abliteration removes refusal, not
      the base priors) — the prior revision was stale (referenced a
      third-party 9B huihui/Ollama model, predating the published organ).
- [x] 6.2 `openspec validate kaine-abliterated-organ --strict` passes;
      abliteration tooling runs in an external environment that imports no
      `kaine` runtime code.

## 7. Follow-up (separate change)

- [x] 7.1 `abliterated-organ-default`'s shipped default points at the
      published KAINE organ (`config/kaine.toml` `[lingua].model_id` =
      `kaineone/Qwen3.5-4B-abliterated-GGUF`); the eval baseline derives from
      it (parity preserved) — shipped via PR #29
      (`feat/abliterated-organ-default`).
