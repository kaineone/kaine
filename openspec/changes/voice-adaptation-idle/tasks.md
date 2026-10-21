## 1. Implementation

- [x] 1.1 Sleep: build pairs only behind the validated-source gate; drop the consolidation metric, its event, its record and its embedder; keep the sleep index
- [x] 1.2 Lifecycle: drop the consolidation arm from `assess_divergence`, the preservation monitor, the decommission CLI and the dashboard
- [x] 1.3 Config and research log: remove the two thresholds and the event's curation
- [x] 1.4 Tests: no pairs, record or event without a validated source; the remaining arms unchanged; existing tests moved off the removed metric
- [x] 1.5 Docs
