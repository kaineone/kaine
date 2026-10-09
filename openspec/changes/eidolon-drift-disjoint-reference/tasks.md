## 1. Disjoint reference

- [x] 1.1 `SourceDistributionDrift` keeps a reference counter of batches evicted from the recent window; the score compares the recent histogram with the reference histogram.
- [x] 1.2 The score is 0.0 until the reference holds at least `window` evicted batches.
- [x] 1.3 `DriftResult.reference_count` and the `eidolon.drift` payload field `reference_count`; `historical_count` stays the all-time event count.
- [x] 1.4 Tests: stable mix scores low; a shift confined to the window scores higher than under the old mixture reference (regression against the old formula); no score before the reference fills; counts consistent; mutation-check.
- [x] 1.5 Docs: `docs/09-modules/eidolon.md`.
- [x] 1.6 `openspec validate eidolon-drift-disjoint-reference --strict`.
