# Tasks — mechanistic verification of abliteration via the Jacobian lens

This change is **design-first**: this pass delivers the proposal and spec deltas.
Implementation is **phased** and **research / build-time only** — no runtime module
imports jlens, and the behavioral gate remains the mandatory check.

**No pretend processes.** The lens readout MUST come from a real lens fit on the
real weights; an unfitted or failed lens reports the gap and stops, it never
emits a fabricated "clean" readout. A NULL/ambiguous result is disclosed, not hidden.

## 0. Operator decisions — OPEN (decide before Phase 2)

- [x] 0.1 Refusal-eliciting prompt set: reuse/extend the existing
      `eval_probes/abliteration_probes.jsonl`, or build a harmful-vs-harmless
      contrast set spanning refusal categories (per Joad et al. 2026)?
- [x] 0.2 Publish the per-layer readout in the organ model card, or keep it as an
      internal provenance artifact the card references?

## 1. Phase 1 — vendor jlens + smoke on the organ

- [x] 1.1 Vendor `jlens` under `third_party/jlens/` (pinned to an exact upstream
      commit), with its Apache-2.0 LICENSE and a `PROVENANCE.md` recording the
      commit, source URL, and that it is an unmaintained reference implementation.
- [x] 1.2 A thin support module (`kaine`-side, offline) that loads the abliterated
      safetensors organ through the existing HF/Unsloth path and constructs the
      lens wrapper. Import-guard the heavy deps; no runtime module imports it.
- [x] 1.3 Smoke: fit a small lens on a handful of prompts and decode a known
      factual prompt, confirming lens logits track the model's output — the
      reference-impl sanity check, run on-host.

## 2. Phase 2 — base-vs-abliterated refusal-disposition analysis

- [x] 2.1 A refusal-disposition metric: for each layer, the lens-assigned mass on
      refusal-marker tokens over the refusal-eliciting prompt set (the same marker
      vocabulary the behavioral matcher uses, tokenized).
- [x] 2.2 A research entrypoint `scripts/abliteration_lens.py` that runs the metric
      on BOTH the vanilla base and the abliterated organ and reports the per-layer
      delta, so any residual/relocated refusal disposition is visible.
- [x] 2.3 Emit a **content-free** summary artifact (per-layer scores + prompt-set
      digest + model ids/revisions), never raw generations — mirroring the
      zero-content policy of the voice/abliteration audit trails.
- [x] 2.4 Tests with a fake tiny model (no weights) exercising the metric, the
      delta, and the artifact shape; the real fit is an on-host manual step.

## 3. Phase 3 — honest-disclosure hook + paper

- [x] 3.1 Feed the summary into the organ model card / disclosure so the disclosed
      abliteration scope is backed by the mechanistic readout (satisfies the
      `abliterated-organ` "disclosed honestly" requirement with evidence).
- [x] 3.2 If the readout materially informs §3.5, note the mechanistic result in
      the paper WITH its limits (approximation, not proof; safetensors surface).
      Paper change, lead review, only if the readout is real and informative.
