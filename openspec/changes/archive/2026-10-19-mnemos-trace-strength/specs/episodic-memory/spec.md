## ADDED Requirements

### Requirement: Persisted traces carry a strength
Each trace in the episodic memory module's persisted collections SHALL carry a strength
$h_i\in(0,1]$, stored as `log_base` in its payload with
$h_i=\exp(\texttt{log\_base}_i+L)$, where $L$ is the store's log gain kept in
a meta record beside the embedding-space stamp with the sleep count, the total
strength and the entity time of the last sleep. A trace SHALL be persisted at
strength 1 with `born_sleep` set to the current sleep count and `entity_time`
set to its storage time on the entity clock. `entity_time` SHALL continue
across restarts. A caller's payload SHALL NOT set `log_base`, `born_sleep` or
`entity_time`. `payload["timestamp"]` SHALL stay wall-clock time. A trace is
below the floor when $h_i<h_{\min}$; no such trace SHALL exist while the entity is awake.

#### Scenario: A persisted trace starts at full strength
- **WHEN** a trace is persisted
- **THEN** its strength is 1, its `born_sleep` is the current sleep count, it
  carries an `entity_time`, and reserved keys in the caller's payload are
  ignored

#### Scenario: Storage times continue across a restart
- **WHEN** the episodic memory module restarts in the middle of a wake and stores another trace
- **THEN** that trace's `entity_time` is later than every trace stored earlier
  in the same wake

### Requirement: Sleep downscales strengths and protects replayed traces
`EpisodicMemoryCore.downscale(protect)` SHALL count $N_{\rm new}$, the persisted traces
with `born_sleep` equal to the sleep count, and SHALL multiply the strength of
every persisted trace outside `protect` by
$\varrho^{N_{\rm new}/N_{\rm day}}$, where $\varrho$ is
`[episodic_memory.strength].retention_per_day` and $N_{\rm day}$ is
`[episodic_memory.strength].traces_per_day`, default 288,000 (86400 x f0 with the
paper's f0 = 10/3). The traces in `protect` SHALL keep
their strength. It SHALL NOT change any vector. It SHALL write the new meta
before it writes the protected traces, so a crash between the two can only
remove strength. It SHALL return `n_new`, `factor`, `protected`,
`total_before`, `total_after`, `pruned_floor`, `pruned_budget` and
`store_bytes`.

#### Scenario: One day of storage keeps the retention fraction
- **WHEN** $N_{\rm day}$ traces were stored since the last sleep and nothing is
  replayed
- **THEN** every older trace keeps the fraction $\varrho$ of its strength

#### Scenario: A sleep after an empty wake changes nothing
- **WHEN** no trace was stored since the last sleep
- **THEN** the factor is 1 and no strength changes

#### Scenario: Protected traces keep their strength
- **WHEN** a sleep protects some traces
- **THEN** their strengths are unchanged, the ratios among the other traces are
  unchanged, and the total strength falls

### Requirement: Recall ranks by strength times similarity
Recall from a persisted collection SHALL return the requested number of
traces with cosine similarity above 0, in decreasing order of
strength times similarity, exactly relative to the backend's cosine order, and
SHALL change no strength. Each result SHALL report `similarity`, `strength`
and `score`, the product. Short-term traces SHALL rank by similarity alone.
On sqlite-vec the search SHALL filter by collection inside the vector index
and SHALL page past the extension's limit of 4096 rows.

#### Scenario: The stronger of two equally similar traces ranks first
- **WHEN** two traces have the same similarity to a cue and different strengths
- **THEN** the stronger one ranks first

#### Scenario: Top-k matches brute force
- **WHEN** recall runs on any backend
- **THEN** the results equal a brute-force ranking by strength times similarity

#### Scenario: sqlite-vec with other collections and more than 4096 rows
- **WHEN** other collections hold rows nearer the cue and the target collection
  needs more than 4096 rows to be searched
- **THEN** recall still returns the requested number of traces from the target
  collection, in the right order

### Requirement: Sleep prunes at the floor and to the storage budget
After the downscaling, in the same call, the episodic memory module SHALL delete every persisted
trace with $h_i<h_{\min}$ (`[episodic_memory.strength].prune_floor`), and then, while
the stores' size $S$ exceeds `[episodic_memory].storage_budget_bytes`, the trace outside
the protected set with the lowest strength, the oldest by `entity_time` first
among equal strengths, stopping when $S$ fits or only protected traces remain.
$S$ SHALL be the sum over persisted traces of `size_bytes`, the record's
float32 embedding plus its serialized text, payload and affect, kept in the
meta record. No trace SHALL be deleted at any other time. The sleep summary
SHALL carry `memory_pruned_floor`, `memory_pruned_budget` and
`memory_store_bytes`, and the research log SHALL keep them.

#### Scenario: A trace below the floor is pruned in the sleep that weakened it
- **WHEN** a downscaling takes a trace below the floor
- **THEN** that trace is deleted in the same sleep and no remaining trace is
  below the floor

#### Scenario: The budget prunes the weakest, oldest first
- **WHEN** the stores exceed the budget after a sleep's downscaling
- **THEN** the weakest traces are deleted, the oldest first among equal
  strengths, until the stores fit

#### Scenario: Replayed traces are exempt
- **WHEN** the budget is smaller than the replayed traces alone
- **THEN** every other trace is deleted and the replayed ones remain

#### Scenario: Nothing is deleted while awake
- **WHEN** the stores exceed the budget between two sleeps
- **THEN** no trace is deleted until the next sleep

#### Scenario: A preserved bundle is unaffected by later pruning
- **WHEN** a store is captured and then pruned
- **THEN** the captured bundle still holds every trace and restores them

### Requirement: Store size and imports stay consistent with what is stored
The episodic memory module SHALL recompute the stores' size from a scan at initialize and at the
start of every downscaling, and SHALL change it, the total strength and the
pruned counts only after a deletion has succeeded, writing the meta after each
successful deletion. A preservation import SHALL mark the meta as pending
before it replaces any collection and clear the mark only when the imported
meta is written; while the mark is set, downscaling SHALL refuse to run and
initialize SHALL log an error. A strength SHALL be `exp(min(0, log_base + L))`,
and a non-finite sum SHALL be a storage error.

#### Scenario: A failed deletion does not cause over-pruning
- **WHEN** a deletion fails part way through pruning, or the process stops
  there, and the episodic memory module is started again
- **THEN** the stored size equals a scan and the next sleep prunes only what
  the budget requires

#### Scenario: An interrupted import blocks sleep
- **WHEN** an import fails after it began replacing collections
- **THEN** every later sleep is blocked and counted in the sleep summary and
  on the dashboard health board until a later import succeeds or the operator
  runs `python -m kaine.lifecycle.episodic_memory_recover --confirm-keep-current-store`

#### Scenario: Disk growth stays bounded while blocked
- **WHEN** an import is pending and the stores exceed twice the budget
- **THEN** new traces are refused, each refusal is logged and counted, and no
  welfare event is raised

### Requirement: Strength survives migration and preservation
At initialize the episodic memory module SHALL backfill, idempotently, every persisted point
without `log_base` to strength 1 with `born_sleep = -1`, and SHALL write a
missing meta before the backfill. It SHALL refuse a store without the meta
whose points already carry `log_base`. A preservation capture SHALL carry the
meta, and a restore SHALL write it after the collections. A restore of a bundle
without the meta and without `log_base` SHALL backfill it, and a restore of a
bundle without the meta whose points carry `log_base` SHALL fail. Decommission
SHALL delete the meta with the embedding-space stamp.

#### Scenario: A legacy store is migrated once
- **WHEN** a store from before this change is initialized twice
- **THEN** every trace has strength 1 after the first initialize and the second
  changes nothing

#### Scenario: Preservation round trip keeps strengths
- **WHEN** a store with downscaled traces is exported and imported
- **THEN** every trace has the same strength and the meta is the same
