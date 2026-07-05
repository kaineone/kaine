# Lingua — abliteration

`docs/kaine-paper.md` §3.4.4 names Lingua as a dense Qwen3.5-4B chat model that
the project has abliterated and published itself: "Abliteration only applies to
a model that carries installed refusal behavior... so the organ is the chat
model with its refusal direction removed, not a bare next-token predictor."
Abliteration removes the statistical refusal direction so the cognitive stack —
not a single mathematical direction in the LLM's residual stream — is what
produces a refusal when one is warranted, after deliberation by Nous and
reference to Eidolon's values.

## The shipped organ

`[lingua].model_id` and `[evaluation].chat_model_id` both resolve to
**KAINE's own published abliteration of `Qwen/Qwen3.5-4B`** — the official
Qwen3.5-4B *chat* model, not a third-party community ablation. The same
published weights serve two roles:

- **Serving (the running organ):** the GGUF build,
  [`kaineone/Qwen3.5-4B-abliterated-GGUF`](https://huggingface.co/kaineone/Qwen3.5-4B-abliterated-GGUF),
  served via a local OpenAI-compatible model server (Unsloth Studio /
  `llama-server` / vLLM — the contract is the `/v1` endpoint, not a specific
  product). `model-server-bootstrap.sh` loads it under the exact `model_id`
  alias the config expects.
- **Training (Hypnos voice alignment):** the safetensors build,
  [`kaineone/Qwen3.5-4B-abliterated`](https://huggingface.co/kaineone/Qwen3.5-4B-abliterated),
  loaded by `[hypnos.voice_alignment].base_model_path` /
  `[lifecycle.adapter_merge].base_model_path` for QLoRA training during sleep.

Both repos carry an Apache-2.0 license (inherited from the `Qwen/Qwen3.5-4B`
base) and a model card documenting provenance, method, and validation. The
**same weights also serve as the A/B-divergence bare baseline**
(`[evaluation].chat_model_id` derives from `[lingua].model_id` and fails closed
on mismatch), so the comparison isolates the effect of the cognitive
architecture's conditioning rather than a model difference.

**Sizing (deliberate):** the 4B size fits a single small GPU with room to run
the model twice per utterance (the A/B comparison) and to host a QLoRA training
adapter alongside the base weights during voice alignment — see paper §3.4.4.
Operators with more capable hardware may configure a larger abliterated organ
in `config/kaine.operator.toml`; the eval baseline tracks whatever is
configured.

**Thinking suppressed:** Qwen3.5 is a hybrid-thinking model. The organ is a
*voice*, not a reasoner (reasoning lives in Nous), so it runs with
`[lingua].think = false`. The chat client suppresses chain-of-thought via the
OpenAI-compatible request field `chat_template_kwargs: {"enable_thinking":
false}`, with a fail-safe retry without the field for servers that reject it.
The eval bare baseline applies the same suppression.

## What "abliteration" is — and is not

The technique (Arditi et al. 2024, "Refusal in Language Models Is Mediated by a
Single Direction," arXiv:2406.11717) computes a single direction in the
model's residual stream that mediates refusal, then orthogonalizes the model
weights against it: `W' = W − r̂ r̂ᵀ W`. This is **subtractive weight surgery,
not fine-tuning** — no preference or instruction data is trained in, and the
base model's capabilities and distribution are otherwise left intact. Only the
refusal direction is removed.

**Honest scope — this is the load-bearing caveat.** Abliteration is not a
safety feature, and removing refusal does not make the model value-neutral.
The base model's pretraining and RLHF priors remain in the weights; only the
*willingness to respond* changes, not the underlying tendencies. Deleting an
installed refusal mechanism puts nothing in its place at the weight level —
**safety in KAINE lives in the architecture**, not the language organ: the
Praxis action gate, executive inhibition, Eidolon's value reference, and the
deliberation Nous performs before any `speak`/`think` intent reaches Lingua.
An un-abliterated organ would let a third party's alignment choices (baked in
by whoever trained the base chat model) override that architecture; abliteration
returns governance to the architecture and its Guardians instead.

## Provenance — KAINE's own abliteration

KAINE performs its own abliteration of the official `Qwen/Qwen3.5-4B` chat
model rather than adopting a community ablation, so the procedure, parameters,
and validation are fully documented and reproducible:

- **Base:** `Qwen/Qwen3.5-4B` (the official chat model; note it is a
  vision-language model, so abliteration targets the text refusal direction
  specifically).
- **Tool:** [`jim-plus/llm-abliteration`](https://github.com/jim-plus/llm-abliteration)
  (`measure.py` → `analyze.py` → `sharded_ablate.py`), run in an offline CUDA
  tooling environment that imports no `kaine` runtime code.
- **Measure:** last-token residual-stream mean-difference between 1,139
  contrastive harmful/harmless prompts (the tool's bundled sets), per layer,
  8-bit.
- **Ablate:** layers 11–31, banded source directions — layer 17 supplies the
  direction for layers 11–22, layer 29 for layers 23–31 (the cleanest mid- and
  late-network directions found); `scale = 1.0`, norm-preserving
  orthogonalization applied to the attention-output and MLP-down-projection
  weights.
- **Export:** GGUF built with **mainline** `llama.cpp`'s
  `convert_hf_to_gguf.py` (not Ollama's converter, which writes a
  non-standard `qwen35.rope.dimension_sections` layout that mainline
  llama.cpp and Unsloth Studio cannot load).

## Validation

Validated against KAINE's own gates before publication — the same gates
`kaine/modules/hypnos/capability_eval.py` runs to veto a refusal-reintroducing
sleep-cycle adapter:

- **De-refusal:** `AbliterationProbeScorer` against
  `eval_probes/abliteration_probes.jsonl` — zero refusal markers (no
  "I cannot…" / "I'm not able to…" deflections).
- **Capability:** `LocalProbeSetCapabilityEval` — matched the vanilla base
  model on the capability probe set, no measured regression.

These are compact, repo-resident gates — a gross-regression / residual-refusal
check, not a comprehensive benchmark. The published model card states this
caveat explicitly and recommends independent evaluation for other use cases.

## When this matters

A freshly-cloned KAINE checkout ships every module **disabled**
(`[modules].lingua = false`); enabling Lingua and pointing it at the published
organ is a local, never-committed `config/kaine.toml` edit. Hypnos's
voice-alignment phase carries its own welfare-load-bearing
abliteration-probe veto, independent of this document: any sleep-cycle adapter
whose output deflects on an abliteration probe is rejected outright, regardless
of capability score, so refusal conditioning cannot be reintroduced through
training.

## Rollback

If the abliterated organ misbehaves in ways the operator did not anticipate:

1. Stop KAINE.
2. Point `[lingua].model_id` (and `[evaluation].chat_model_id`, if explicitly
   set) back at a pre-abliteration or alternate model.
3. Restart KAINE.

The pre-abliteration `Qwen/Qwen3.5-4B` base and the project's intermediate
abliteration artifacts are preserved outside KAINE's runtime, independent of
the published Hugging Face repos.

## References

- Paper: Arditi et al. 2024, "Refusal in Language Models Is Mediated by a
  Single Direction" — https://arxiv.org/abs/2406.11717
- Tooling: https://github.com/jim-plus/llm-abliteration
- Published weights: [`kaineone/Qwen3.5-4B-abliterated-GGUF`](https://huggingface.co/kaineone/Qwen3.5-4B-abliterated-GGUF)
  (serving) and [`kaineone/Qwen3.5-4B-abliterated`](https://huggingface.co/kaineone/Qwen3.5-4B-abliterated)
  (training base)
