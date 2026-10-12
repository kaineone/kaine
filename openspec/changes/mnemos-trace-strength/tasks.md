## 1. Implementation

- [x] 1.1 Storage: meta records, wake points, filtered counts, log-base writes, backfill and the `min_log_base` search filter on the in-memory, sqlite-vec and Qdrant backends
- [x] 1.2 sqlite-vec: `collection` partition key, distance paging past 4096 with boundary ties, rebuild of an old table, pin `sqlite-vec>=0.1.9`
- [x] 1.3 MnemosCore: strength keys on persist, entity-time stamps that continue across restarts, `downscale(protect)`, recall by strength times similarity, migration, preservation of the meta
- [x] 1.4 Episodic memory and Sleep: replay pool is the wake just ended, phase 2 calls `downscale` and records its summary, `downscale_activations` and `downscale_factor` removed
- [x] 1.5 Config and boot: `[mnemos.strength]`, $N_{\rm day}$ as `[mnemos.strength].traces_per_day` (288,000); decommission deletes the strength meta
- [x] 1.6 Tests on all three backends: persist keys, factor, ratios and protection, vectors untouched, recall order, exact top-k against brute force (sqlite: other collections populated, more than 4096 rows), replay pool regression, migration, preservation round trip, crash order, numerics over many sleeps, clock across a restart, config
- [x] 1.7 Docs: Episodic memory, Sleep, sleep and configuration pages
- [x] 1.8 Pruning (paper PR #29): floor and storage budget at sleep, replayed traces exempt, nothing deleted while awake, store size kept in the meta, counts in the sleep summary and research log; tests on all three backends
- [x] 1.9 Second review: store size from a scan at initialize and each sleep, decremented only after a successful delete; a failed replay skips downscaling; pending-import flag; clamped, finite strengths; bounded recall re-search; sqlite-vec ties paged with `distance >=`; N_day as a config key; decommission keeps the meta when a drop fails
- [x] 1.10 Re-review: a blocked sleep is counted and surfaced in the sleep summary, the research log and a Dashboard health panel; new traces are refused while an import is pending and the store exceeds twice its budget; `python -m kaine.lifecycle.mnemos_recover`; recall widening capped at 4096; total strength self-heals with the size scan; backfill keeps an existing size
