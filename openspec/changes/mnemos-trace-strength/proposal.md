## Why

Paper PR #28 says what sleep downscales (§4 "Episodic memory and sleep", Appendix A.10,
Table A1, and a new limitation). Each persisted episodic memory trace carries a
strength $h_i\in(0,1]$, stored at 1. Each sleep replays a few traces of the
wake just ended, then scales the strength of every other trace by
$\varrho^{N_{\rm new}/N_{\rm day}}$. Replayed traces keep their strength, a
trace below $h_{\min}$ is pruned in that sleep, and recall ranks by $h_i\,\mathrm{sim}_i$. Paper
PR #29 adds the pruning rule and an operator storage budget $B$ in bytes.

The code does not follow it.

1. `EpisodicMemory.downscale_activations` multiplies stored vectors by a fixed 0.9, and
   only on the in-memory backend. Every backend ranks by cosine and Qdrant
   normalizes on upload, so the scaling changes no recall result anywhere.
2. Replay draws on `last_consolidated`, which holds only the traces left in
   the 128-entry short-term buffer when sleep begins. The rest of the wake
   was persisted by eviction and can never be replayed, so the pool is the
   last 40 s or so of a wake of about 12,000 traces.
3. Storage times are wall-clock (`payload["timestamp"]`), while §3.4 and
   Appendix A read all time from the entity clock, and A.10 defines replay
   recency on storage time.
4. The sqlite-vec search applies `k` before the collection filter, so once
   another collection holds rows it returns fewer than `k`, and `k` is capped
   at 4096 by the extension, so a recall that has to look further fails.

## What Changes

- Each persisted trace carries `log_base`, `born_sleep` and `entity_time` in
  its payload. Its strength is $h_i=\exp(\texttt{log\_base}_i+L)$, where $L$
  is a per-store log gain kept in a meta record with the sleep count $n$, the
  total strength $H$ and the entity time of the last sleep. A trace is
  persisted with `log_base = -L` and `born_sleep = n`. One sleep costs one
  meta write plus a point write for each replayed trace, so no sleep rewrites
  every trace. These keys are reserved: a caller's payload cannot set them.
- `MemoryStorage` gains `read_meta`/`write_meta` (beside the embedding-space
  stamp, which validates a different shape), `wake_points`, `count_filtered`,
  `set_log_base`, `backfill_strength`, `total_size`, `weakest` (ascending
  strength, then storage time, tie-complete) and `delete_points`. All three
  backends implement them.
- Phase 2 replays from the whole wake just ended: every persisted trace with
  `born_sleep == n`, plus any short-term entry. Recency runs on `entity_time`.
  `EpisodicMemoryCore.downscale(protect)` then counts $N_{\rm new}$, writes the new
  meta first, gives each replayed trace back its strength, and then prunes:
  every trace below $h_{\min}$, then, while the stores' size $S$ exceeds $B$,
  the weakest trace outside the replayed set, the oldest first among equal
  strengths. $S$ is the sum of each record's `size_bytes` (embedding plus
  serialized payload), kept incrementally in the meta. It returns `n_new`,
  `factor`, `protected`, `total_before`, `total_after`, `pruned_floor`,
  `pruned_budget` and `store_bytes`, which phase 2 puts in its metadata; the
  sleep summary carries the last three at top level for the research log.
  Nothing is deleted while awake. `downscale_activations` is removed.
- Recall on a persisted collection returns the `k` traces with
  cosine above 0 in decreasing order of $h_i\,\mathrm{sim}_i$. It widens its
  fetch until the k-th product is at least the smallest fetched cosine, which
  bounds every unfetched trace since $h\le 1$, so the top k is exact relative
  to the backend's cosine order. `RecalledMemory` gains `similarity` and
  `strength`, and `score` is the product. Short-term recall ranks by cosine
  alone and also drops traces with cosine at or below 0.
- sqlite-vec: the vector table gains `collection` as a partition key, so the
  KNN filters by collection inside the extension, and search pages past 4096
  rows with the `distance` constraint, taking every row tied at a page
  boundary. An old table is rebuilt in one transaction at open. The pin rises
  to `sqlite-vec>=0.1.9,<1`.
- `entity_time` comes from the entity clock and continues across restarts:
  at initialize the episodic memory module resumes from the newest stamp of the current wake, or
  the meta's time of the last sleep. `payload["timestamp"]` stays wall-clock,
  because the live memory prober compares it with the organ's context.
- Migration at initialize is idempotent: a store without the meta gets
  `{log_gain: 0, sleeps: 0, total: count, entity_time: 0}`, written before
  the backfill, and every point without `log_base` gets `log_base = 0`,
  `born_sleep = -1` (strength 1, never in a replay pool). A store without
  the meta whose points already carry `log_base` is refused.
- Preservation: `export_state` carries the meta under `strength`.
  `import_state` writes it after the collections; a bundle without it and
  without `log_base` is an old bundle and is backfilled; a bundle without it
  but with `log_base` is refused, since the offsets mean nothing without $L$.
- Decommission deletes the strength meta with the embedding-space stamp.
- Config: `[episodic_memory.strength]` with `retention_per_day = 0.82` and
  `prune_floor = 0.01`, both in (0, 1), and `[episodic_memory].storage_budget_bytes`
  (default 10 GiB; the paper leaves $B$ to the operator). $N_{\rm day}$ is
  `[episodic_memory.strength].traces_per_day`, default 288,000, the paper's
  86400 x f0 with f0 = 10/3, independent of the tunable cycle rate.
  `[sleep.consolidation].downscale_factor` is removed and its presence fails
  the boot, since it never changed a recall.

## Impact

- The episodic memory module is held, so the base-thesis form is unaffected: with the episodic memory module absent
  phase 2 is skipped as before.
- Affected code: `kaine/modules/episodic_memory/{storage,memory,module,replay}.py`,
  `kaine/modules/sleep/{phases,module}.py`, `kaine/boot/factories/{episodic_memory,sleep}.py`,
  `kaine/memory_kinds.py`, `kaine/lifecycle/decommission.py`,
  `config/kaine.toml`, `pyproject.toml`, docs.
- Known gaps. Phase 3's period buckets and `recent_points` keep the
  wall-clock `timestamp`, since the paper does not specify them.
  Qdrant search is HNSW, so its top k is exact relative to Qdrant's
  approximate cosine list, as recall is today.
