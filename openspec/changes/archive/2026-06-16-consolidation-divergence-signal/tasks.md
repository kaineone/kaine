# Tasks (design-first proposal — implement on approval)

## 1. Emit the metric
- [x] 1.1 Compute `records_scanned`/`usable_pairs`/`divergence_rate` in the voice-alignment phase (the DPO build already has the counts); add `divergence_magnitude` = mean cosine distance over the kept pairs via the semantic embedder (reuse the A/B meter's embedder; null when unavailable).
- [x] 1.2 Emit even when training is skipped/disabled or the adapter is rejected (divergence is independent of training success).
- [x] 1.3 Publish a content-free `hypnos.consolidation_divergence` bus event + research-log record (aggregates only; NEVER prompt/chosen/rejected text).

## 2. Consume it (graded divergence)
- [x] 2.1 `assess_divergence()` reads the latest consolidation divergence and treats rate/magnitude over threshold as an organ-level divergence condition; `adapters_present` demoted to a weaker secondary signal. Numeric values in `DivergenceAssessment.signals`.
- [x] 2.2 Config thresholds (rate + magnitude), shipped conservative.

## 3. Surface
- [x] 3.1 Nexus entity-care/divergence panel shows rate + magnitude + trend (numeric/content-free).
- [x] 3.2 Research event log taxonomy entry (numeric allowlist).

## 4. Tests + docs
- [x] 4.1 Tests per design (counts/rate/magnitude correctness; emitted-when-skipped; content-free; assess_divergence flips on threshold; privacy; Nexus numeric-only).
- [x] 4.2 Docs: present-tense — the consolidation divergence signal as the cheap continuous organ-level companion to the individuation permutation test.
- [x] 4.3 Full suite green; `openspec validate --strict`.
