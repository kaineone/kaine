## Why

The paper (Appendix A.10, *Associative replay*, and §4, predictive-workspace-paper #47) now states associative replay as a rule on the episodic stores: overlapping replay of related memories may strengthen their shared elements and build schemata (Lewis and Durrant 2011), and sleep both integrates new items into schemata and combines items into new ones (Stickgold and Walker 2013). Each sleep co-replays a few pairs of a replayed trace and a related older one and records the pair as a weighted link. The code's phase 3 does something else: it buckets traces by time, cues the world model for scenarios and re-injects them as `sleep.association` events, and stores nothing. The paper's rule keeps no world-model cue.

## What Changes

- After downscaling, each sleep co-replays at most `n_pair` pairs, most similar first, of a trace in the replayed set `Q` and one stored before the wake window `W`, with `sim_min <= sim < sim_dup` (cosine similarity, as in recall). Defaults from Table A1: `n_pair = 5`, `sim_min = 0.5`, `sim_dup = 0.95`, `n_sch = 3`, `n_link = 8`, set in a new `[episodic_memory.association]` table.
- Each co-replay sets the pair's link weight `w` to `(1 + w) / 2`, from `w = 0` before the first. A link is stored as a record of its own with a `log_base` on the same gain as trace strengths, so downscaling scales `w` by the factor that scales `h_i`.
- Recall of either member of a link also returns the other.
- A trace with at least `n_sch` links forms a schema node: a record whose embedding is the centroid of the trace's and its partners' embeddings and whose strength is their mean link weight. Recall ranks nodes with the traces by strength times similarity.
- Each trace keeps at most `n_link` links; the weakest go first. Links and nodes count in the store size `S` and are pruned as traces are, at the floor and for the budget, and a deleted trace takes its links. Their number therefore grows at most linearly with the traces, and the budget `B` bounds them with the traces.
- Pruning moves after associative replay, as A.10 orders it: when phase 3 is on, phase 2 downscales without pruning and phase 3 prunes after the co-replays. When phase 3 is off, phase 2 downscales and prunes exactly as before.
- Phase 3 no longer cues the world model and no longer selects traces by time period. `select_cross_period_traces` and `[episodic_memory.replay].cross_period_candidates` are removed. The `sleep.association` event now carries the pair's point ids and its weight, and no content.
- Links and nodes live in two persisted collections, `<prefix>links` and `<prefix>schemas`, that are created on the first co-replay. Preservation exports them and revive restores them with the trace collections, in the same embedding space under the same stamp; decommission covers them.
- Phase 3 stays off by default (`[sleep.consolidation].associative_replay = false`). A store that has never had a co-replay has no association collections, and with the flag off every behaviour is the same as before.

## Capabilities

### Modified Capabilities

- `episodic-memory`: associative links between traces, schema nodes, link-aware recall, and pruning and persistence of both.
- `hypnos-consolidation`: phase 3 is the paper's associative replay; the world-model scenario cue and the cross-period selection are removed.

## Impact

- `kaine/modules/episodic_memory/storage.py` (new `get_points` on every backend), new `kaine/modules/episodic_memory/associations.py`, `kaine/modules/episodic_memory/memory.py`, `kaine/modules/episodic_memory/module.py`, `kaine/memory_kinds.py`, `kaine/lifecycle/decommission.py`, `kaine/boot/factories/episodic_memory.py`, `kaine/modules/sleep/phases.py`, `kaine/modules/sleep/module.py`, `kaine/faithful/templates.py`, `config/kaine.toml`.
- Docs: `docs/09-modules/episodic-memory.md`, `docs/09-modules/sleep.md`, `docs/10-sleep/README.md`, `docs/appendix-a-configuration/`.
- Tests: new storage, association and phase-3 tests; the cross-period tests are removed with the selection.
- Behaviour: none with the default configuration. With phase 3 on, the store gains a bounded number of link and node records, and recall can return linked partners and schema nodes.
