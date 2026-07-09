# Mechanistic verification of abliteration via the Jacobian lens

## Why

The organ's abliteration is validated **behaviorally**: the
`AbliterationProbeScorer` (and the provisioning gate that now runs it across the
built safetensors and the served GGUF) confirms the organ does not *emit* refusal
markers on a probe set. That is necessary but not sufficient. Refusal is not one
clean direction — it is a multi-dimensional, category-structured behavior
(Wollschläger et al. 2025; Joad et al. 2026), so a model can pass a bounded
behavioral battery while a refusal *disposition* survives internally, merely
suppressed at the output or relocated to an unprobed category. A behavioral gate
cannot see that; a mechanistic, layer-resolved check can.

The Jacobian lens (Gurnee et al. 2026) decodes what an internal activation is
*disposed to make the model say* at any layer and position, by transporting it
into the final-layer basis with an averaged input–output Jacobian and reading it
through the unembedding. Running the lens on the organ over refusal-eliciting
prompts, and **comparing the vanilla base model against its abliterated
counterpart layer by layer**, shows directly whether the refusal disposition is
removed or whether a residual persists at some depth. This turns the honest
disclosure the `abliterated-organ` capability already requires ("do not overclaim
a clean substrate") from an assertion into evidence, and it strengthens the
paper's §3.5 position on exactly the axis the multi-dimensional-refusal literature
puts pressure on.

This is a **design-first** change and a **research / build-time** capability. It
does not touch the runtime cognitive loop, and it does not replace the behavioral
gate — it complements it. The lead reviews this design before any code lands.

## What Changes

- **Vendor the Jacobian lens reference implementation.** `jlens` is Apache-2.0 but
  explicitly unmaintained and not accepting contributions, so a **pinned, vendored
  copy** (under `third_party/jlens/` with its LICENSE and a provenance note) is
  taken rather than a package dependency, and its exact upstream commit is
  recorded. No runtime module imports it.
- **A base-vs-abliterated refusal-disposition analysis tool.** An offline research
  entrypoint fits a Jacobian lens on the abliterated safetensors organ (and,
  once, on the vanilla base), runs a refusal-eliciting prompt set through both,
  and reports, per layer, the mass the lens places on refusal-marker tokens — so
  the delta between base and abliterated makes any residual refusal disposition
  visible. It emits a content-free summary artifact (per-layer disposition
  scores + the prompt-set digest), never raw generations.
- **The honest-disclosure hook.** The summary feeds the organ's model card /
  disclosure so the disclosed abliteration scope is backed by a mechanistic
  readout, satisfying the existing `abliterated-organ` disclosure requirement with
  evidence rather than assertion.

## Capabilities

### New Capabilities

- `abliteration-interpretability`: a mechanistic, layer-resolved analysis of the
  organ's refusal disposition using the Jacobian lens; a vanilla-base vs
  abliterated comparison over a refusal-eliciting prompt set; a content-free
  summary artifact; and an explicit statement of the method's limits (the lens is
  an averaged-Jacobian approximation and an interpretive signal, not a proof of
  complete removal). Offline and non-runtime.

### Modified Capabilities

- `abliterated-organ`: the "abliteration scope is disclosed honestly" requirement
  additionally admits a mechanistic Jacobian-lens readout as supporting evidence
  for the disclosed scope, alongside the behavioral probe result. The behavioral
  gate remains mandatory; the lens readout is corroborating, not a substitute.

## Impact

- **Depends on:** `abliterated-organ` (the artifact under analysis and its
  disclosure), `organ-provisioning` (the same safetensors base the build gate
  loads), `voice-alignment-training` (the Unsloth/HF stack and the probe set are
  reused). All shipped.
- **Repo (at implementation time):** adds `third_party/jlens/` (vendored, pinned),
  a research entrypoint under `scripts/` (e.g. `scripts/abliteration_lens.py`) and
  a thin support module, plus tests with a fake tiny model so the analysis logic
  runs without weights. No entity is booted; no runtime module imports jlens.
- **Dependencies:** PyTorch + HuggingFace `transformers` (already present via the
  `[training]` extras). No new runtime dependency; the vendored lens is used only
  by the offline tool.
- **Honest limits (load-bearing, must be stated in outputs and any paper use):**
  the lens is an averaged-Jacobian approximation and an interpretive signal, not a
  proof of complete removal; it runs on the **safetensors** model (the served GGUF
  is covered by the behavioral gate's served surface, not by the lens); fitting
  costs backward passes over ~100–1000 prompts (one-time, on-host). A NULL or
  ambiguous readout is reported honestly, never suppressed.
- **Behavior:** no runtime behavior changes. A new offline research artifact and a
  stronger, evidence-backed disclosure.

## Open questions (for the lead)

- The refusal-eliciting prompt set: reuse/extend `eval_probes/abliteration_probes.jsonl`,
  or a purpose-built harmful-vs-harmless contrast set spanning refusal categories?
- Whether the per-layer readout (and any visualization) is published in the organ
  model card, or kept as an internal provenance artifact referenced by the card.
