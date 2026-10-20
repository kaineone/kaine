## 1. Fresh-phase coherence

- [x] 1.1 `CoherenceScorer.observe` records a per-sample freshness flag (phase differs from that module's previous sample; a non-finite phase is not fresh).
- [x] 1.2 Pairwise PLV in `factor_for_source` and `plv` uses only jointly fresh ticks; fewer than `MIN_FRESH_SAMPLES` gives the neutral PLV that maps to factor 1.0; a source with no partner gets factor 1.0.
- [x] 1.3 Tests: frozen phases give factor 1.0, not the ceiling; a lone source gets 1.0; two rotating locked sources still beat a desynchronized pair; the neutral PLV maps to exactly 1.0; mutation-check each.
- [x] 1.4 The oscillatory-ablation runner and its tests still pass, or their expectations are updated with a stated reason.
- [x] 1.5 Docs: `docs/08-cognitive-cycle/global-workspace.md`.
- [x] 1.6 `openspec validate coherence-fresh-phases --strict`.
