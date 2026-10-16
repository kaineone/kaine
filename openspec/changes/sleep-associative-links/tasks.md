## 1. Implementation

- [x] 1.1 Storage: `get_points(collection, ids, with_vectors)` on the in-memory, sqlite-vec and Qdrant backends, with tests on all three
- [x] 1.2 Pure association rules (link ids, weight update, link cap, schema node centroid and strength) in `kaine/modules/episodic_memory/associations.py`, with tests
- [x] 1.3 Episodic memory core: association collections and index, `downscale(prune=False)`, `associate()`, `prune()` with links and nodes in `S` and the cascade, link-aware recall, export and import, with tests on all three backends
- [x] 1.4 Episodic memory module and boot: `associate()` and `prune()`, `[episodic_memory.association]` keys, removal of `select_cross_period_traces` and `cross_period_candidates`, decommission covers the association collections
- [x] 1.5 Sleep: phase 2 defers pruning when phase 3 is on; phase 3 calls `associate()` then `prune()` and publishes `sleep.association` with pair ids and weight; no world-model cue; faithful template; tests including the flag-off identity
- [x] 1.6 Docs and config comments: episodic memory, sleep, configuration appendix
