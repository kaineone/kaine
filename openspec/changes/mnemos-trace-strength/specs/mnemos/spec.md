## ADDED Requirements

### Requirement: Persisted traces carry a strength
Each trace in Mnemos's persisted collections SHALL carry a strength
$h_i\in(0,1]$, stored as `log_base` in its payload with
$h_i=\exp(\texttt{log\_base}_i+L)$, where $L$ is the store's log gain kept in
a meta record beside the embedding-space stamp with the sleep count, the total
strength and the entity time of the last sleep. A trace SHALL be persisted at
strength 1 with `born_sleep` set to the current sleep count and `entity_time`
set to its storage time on the entity clock. `entity_time` SHALL continue
across restarts. A caller's payload SHALL NOT set `log_base`, `born_sleep` or
`entity_time`. `payload["timestamp"]` SHALL stay wall-clock time. A trace is
silent when $h_i<h_{\min}$; no trace SHALL be deleted for being silent.

#### Scenario: A persisted trace starts at full strength
- **WHEN** a trace is persisted
- **THEN** its strength is 1, its `born_sleep` is the current sleep count, it
  carries an `entity_time`, and reserved keys in the caller's payload are
  ignored

#### Scenario: Storage times continue across a restart
- **WHEN** Mnemos restarts in the middle of a wake and stores another trace
- **THEN** that trace's `entity_time` is later than every trace stored earlier
  in the same wake

### Requirement: Sleep downscales strengths and protects replayed traces
`MnemosCore.downscale(protect)` SHALL count $N_{\rm new}$, the persisted traces
with `born_sleep` equal to the sleep count, and SHALL multiply the strength of
every persisted trace outside `protect`, silent traces included, by
$\varrho^{N_{\rm new}/N_{\rm day}}$, where $\varrho$ is
`[mnemos.strength].retention_per_day` and $N_{\rm day}$ is
`86400 * [cycle].experiential_rate_hz`. The traces in `protect` SHALL keep
their strength. It SHALL NOT change any vector. It SHALL write the new meta
before it writes the protected traces, so a crash between the two can only
remove strength. It SHALL return `n_new`, `factor`, `protected`,
`total_before`, `total_after` and `silent`.

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
non-silent traces with cosine similarity above 0, in decreasing order of
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

#### Scenario: Silent traces are not recalled
- **WHEN** a trace's strength is below the silence floor
- **THEN** recall does not return it and it stays in the store

### Requirement: Strength survives migration and preservation
At initialize Mnemos SHALL backfill, idempotently, every persisted point
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
