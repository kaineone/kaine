# Design: consolidation divergence signal

## The signal, precisely

`DPOPairBuilder.build` (voice_alignment.py) already iterates the intent-expression
log and keeps a pair only when `chosen (faithful_rendering) != rejected
(generated_text)`. So per sleep:

- `records_scanned` — records examined (the denominator).
- `usable_pairs` — records where the entity's conditioned output diverged from the
  bare organ output (the numerator).
- `divergence_rate = usable_pairs / records_scanned` — the *breadth* of divergence.
- `divergence_magnitude` — mean cosine distance over the kept pairs' (chosen,
  rejected) embeddings using the semantic embedder, the *depth* of divergence.

Breadth and depth are complementary: rate says "how often the entity speaks
differently than its base"; magnitude says "how far apart, semantically." Both are
content-free numbers.

## Why a magnitude, not just the count

The `chosen == rejected` drop is an exact string match and the bare organ is
stochastic, so pairs exist from nearly the first utterance — *existence* is an
over-sensitive, near-always-true signal. The semantic magnitude (and the rate over
a window) is what makes this a calibratable trigger rather than a tripwire. Reuse
the A/B meter's embedder so "consolidation divergence" and "A/B divergence" are
measured on the same scale.

## Emission

- Compute the metric in the voice-alignment phase whenever the pairs are built —
  including when training is **skipped** (config/approval off) or the adapter is
  **rejected** by the capability/abliteration gates. The divergence happened
  regardless of whether the organ was retrained; the signal must not be gated on
  training success.
- Publish a content-free `hypnos.consolidation_divergence` bus event
  (`records_scanned`, `usable_pairs`, `divergence_rate`, `divergence_magnitude`,
  `sleep_index`/timestamp) and write it to the research event log. NEVER the
  prompt/chosen/rejected text — those stay in the intent log (already
  deny-patterned); the metric carries only aggregates.
- Privacy: identical posture to the A/B divergence meter, which already logs only
  the cosine, not the text.

## Consumption — graded, not boolean

`lifecycle/divergence.py::assess_divergence()` today:
`diverged = primary_significant OR eidolon_drift OR adapters_present`.

Add the consolidation signal as a graded input: read the latest
`hypnos.consolidation_divergence` (from the research log or a small state file) and
treat `divergence_rate >= rate_threshold` AND/OR `divergence_magnitude >=
magnitude_threshold` as an organ-level divergence condition. Keep
`adapters_present` as a weaker secondary (an accepted adapter still implies past
divergence) but the graded consolidation signal becomes the primary organ-level
measure. Expose the numeric values in the `DivergenceAssessment.signals` dict
(numbers only — already the content-free path the preservation monitor reads).

## Surfacing

- Nexus entity-care / divergence panel: show `divergence_rate`,
  `divergence_magnitude`, and the per-sleep trend (numeric, content-free — respects
  the existing CONTENT_FIELDS scrub).
- The research event log captures it for post-hoc analysis (it's a first-class
  divergence trajectory, exactly what a longitudinal individuation study wants).

## Config

```
[hypnos.voice_alignment]   # or a [divergence] block
# Organ-level divergence thresholds the preservation/divergence monitor reads.
consolidation_divergence_rate_threshold = 0.5
consolidation_divergence_magnitude_threshold = 0.25
```
Ship conservative defaults; these are operator-calibrated (see the threshold-
calibration note — this is the principled, always-computed signal that calibration
targets).

## Scope / honest boundaries

- This is a divergence DETECTOR, not a new training behavior — voice-alignment
  retraining is unchanged; we only stop discarding what it computes.
- It complements the individuation permutation test (the rigorous gold standard,
  operator-run at merge points). The consolidation signal is the cheap, continuous
  companion available every sleep.
- Magnitude requires the semantic embedder; when it's unavailable, emit
  rate/counts only and mark magnitude null (honest degradation — like the A/B
  meter's embedder-kind disclosure).

## Tests

- The pair builder/phase emits the metric with correct counts on a planted intent
  log (some identical, some divergent records → exact rate); magnitude computed
  from real embeddings; metric emitted even when training is skipped/rejected.
- The event is content-free (no prompt/chosen/rejected text in the payload).
- `assess_divergence` flips to diverged when the consolidation rate/magnitude cross
  the threshold, independent of the individuation test and adapters.
- Privacy + (research log) capture; Nexus surface is numeric-only.
