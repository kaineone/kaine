# Consolidation divergence signal — surface the organ-level divergence sleep already computes

## Why

Every voice-alignment sleep phase already computes the exact divergence between
the entity's whole-cognition output and its bare language organ — and then throws
it away. `kaine/modules/hypnos/voice_alignment.py::DPOPairBuilder.build` reads the
intent-expression log and forms a preference pair only where
`faithful_rendering` (the workspace-conditioned output) differs from
`generated_text` (the bare organ generation), dropping every record where
`chosen == rejected` ("no signal to train on"). A *usable pair therefore exists
iff the entity diverged from its base model on a lived utterance* — which is
exactly the A/B divergence signal, materialized as training data.

This is the most concrete, organ-level evidence of individuation there is: a sleep
cycle "has a reason to retrain Lingua" precisely when divergence has occurred, and
the training then folds that divergence into the organ's weights. Yet:

- The pair count is computed and discarded — only the accept/reject result and
  `samples_used` survive in the `TrainingResult`. It is never emitted as a metric.
- `lifecycle/divergence.py::assess_divergence()` — the function the preservation
  monitor uses — treats only the *downstream, accepted* `adapters_present` boolean
  as an organ-level divergence signal. The *upstream* evidence (usable pairs
  existed, i.e. the consolidation found something to align) is invisible, and the
  boolean is coarse (it flips only after training succeeds AND the adapter passes
  the capability + abliteration gates).

So the cheapest, always-available, organ-level divergence measure in the system is
silently dropped, and the divergence trigger runs on a coarser proxy.

## What Changes

- The voice-alignment phase emits a **content-free consolidation divergence
  metric** per sleep: `usable_pairs` (count), `records_scanned` (denominator),
  `divergence_rate` (usable / scanned), and a **semantic magnitude** — the mean
  cosine distance over the pairs using the existing semantic embedder
  (`kaine/evaluation/embeddings.py`), the same machinery the A/B meter uses — so
  the signal is a calibrated magnitude, not just a binary "pairs exist". Emitted
  even when training is skipped/disabled (the pairs are built regardless), and even
  when the adapter is rejected (the divergence still happened). Numbers and a
  scalar only — never the `chosen`/`rejected` utterance text (that lives in the
  intent log, already deny-patterned).
- `assess_divergence()` consumes it as a **graded** organ-level divergence input
  alongside the individuation permutation test and Eidolon drift — a
  `divergence_rate`/magnitude over a configured threshold, replacing reliance on
  the coarse `adapters_present` boolean (kept as a weaker secondary signal).
- The metric is logged (research event log) and surfaced in Nexus (the entity-care
  / divergence panel), so an operator can watch organ-level divergence accrue.

## Impact

- Affected: `kaine/modules/hypnos/` (emit the metric), `kaine/lifecycle/divergence.py`
  (consume it), the research event observer taxonomy, Nexus health/entity-care,
  config (the divergence-rate/magnitude threshold).
- Feeds the existing preservation/divergence monitor — gives it a continuous,
  always-computed organ-level trigger instead of the coarse adapter boolean, which
  is exactly the calibrated signal the threshold-calibration work needs.
- Privacy-safe: counts + a scalar magnitude only; rides the existing content-free
  metric path; the intent-log text is never exposed.
- Complements, does NOT replace, the individuation permutation test — that remains
  the rigorous statistical instrument; this is the cheap, continuous companion.
