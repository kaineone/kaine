## MODIFIED Requirements

### Requirement: Top-k coalition selection
`Workspace.select` SHALL return a `WorkspaceSnapshot` whose
`selected_events` is the top `top_k` events by salience, ordered
descending. The default `top_k` SHALL be 1, one accessed content per broadcast,
and SHALL be configurable at construction time and adjustable at runtime via
`set_top_k`. The shipped configuration SHALL set `top_k = 1`.

#### Scenario: Top-1 of ten events
- **WHEN** ten events are presented with distinct salience scores and the default capacity
- **THEN** the returned snapshot contains exactly the highest-scoring event

#### Scenario: Top-5 of ten events
- **WHEN** ten events are presented with distinct salience scores and `top_k=5`
- **THEN** the returned snapshot contains exactly five events in
  descending salience order

#### Scenario: Fewer events than k
- **WHEN** two events are presented with `top_k=5`
- **THEN** the snapshot contains both events without padding

### Requirement: Broadcasts carry the access threshold
Every competitive and matched broadcast SHALL record the access threshold in its metadata under `access_threshold`, and every broadcast SHALL name its accessed members under `accessed_ids`. In the competitive arm the accessed members are the coalition members whose score reaches the threshold; in the matched arm they are the drawn members, whatever their score; in the pooled arm they are every member. Processors SHALL take the members named in `accessed_ids` as accessed content and SHALL NOT re-apply the threshold. A broadcast is accessed when at least one member is.

#### Scenario: A rider below the threshold is not accessed
- **WHEN** a competitive broadcast's coalition has members scoring 0.5 and 0.1 with an access threshold of 0.35
- **THEN** its metadata records the threshold 0.35, and only the member scoring 0.5 is in `accessed_ids`

#### Scenario: A drawn member below the threshold enters the context
- **WHEN** the matched arm draws a member scoring 0.1 against a threshold of 0.35
- **THEN** the member is in `accessed_ids` and enters the processors' context

## REMOVED Requirements

### Requirement: The matched arm draws a score-blind coalition of the competitive size
**Reason**: Drawing `min(top_k, n)` members and then applying the threshold makes the matched arm equal the competitive arm whenever the pool is no larger than the capacity, and once capacity binds it changes how often access happens instead of what is accessed. Replaced by "The matched arm is count-yoked to the competitive selection".
**Migration**: Matched-arm runs recorded before this change used the old rule; their records carry `coalition_capacity` and no `matched_counterfactual`, so readers can tell them apart. No pilot or live run of the planned test has been run.

## ADDED Requirements

### Requirement: The matched arm is count-yoked to the competitive selection
On a broadcast tick the matched arm SHALL score every candidate, compose the competitive selection over the same scores as a counterfactual, and be inhibited when it is. Otherwise, with `a` its accessed count, it SHALL draw `a` candidates uniformly without replacement, regardless of score, from a generator seeded from the run seed, order them by score and access all of them. The score table SHALL hold every candidate's score.

#### Scenario: Access follows the competitive selection
- **WHEN** a broadcast tick has six candidates, `top_k=1`, and the best scores 0.9 against a threshold of 0.35
- **THEN** the matched snapshot is not inhibited and has one member drawn from the six, whatever its score

#### Scenario: Inhibition follows the competitive selection
- **WHEN** every candidate scores below the threshold
- **THEN** the matched snapshot is inhibited and draws no member

#### Scenario: The same seed reproduces the draws
- **WHEN** two matched runs with the same seed see the same broadcast ticks
- **THEN** they draw the same coalitions

### Requirement: The matched arm draws only on broadcast ticks and keeps no generator state
A tick that is not a broadcast tick SHALL draw nothing, and a context that does not say whether the tick is a broadcast tick SHALL be refused rather than fall back to top-k selection. The generator's state SHALL NOT be persisted: the draws are reproducible within one uninterrupted run, and a restart or revive starts the stream again from the seed.

#### Scenario: A matched selection without the broadcast flag is refused
- **WHEN** a matched `select` is called with a context that has no `is_experiential` key
- **THEN** it raises `ValueError`

### Requirement: A matched snapshot carries its counterfactual without content
A matched snapshot SHALL carry, in its metadata, the content-free comparison of its drawn membership with the counterfactual's: the membership divergence, the counterfactual's accessed count and its inhibition.

#### Scenario: The counterfactual is logged without content
- **WHEN** a matched broadcast is composed
- **THEN** its metadata carries the membership divergence, the accessed count and the inhibition of the counterfactual, and no event id or payload of the counterfactual

### Requirement: Novelty is evaluated once per report
The salience strategy SHALL observe a candidate's novelty once, on the first tick it is scored, and SHALL reuse that value on every later tick while the report is held, keyed by its stream-qualified id. The cached value SHALL be dropped when the report leaves the pool.

#### Scenario: A held report keeps its novelty
- **WHEN** a report scored with novelty 1.0 is held for five ticks
- **THEN** its novelty is 1.0 on every tick and the novelty window received one observation of it

### Requirement: A held report is scored with the current gains
On every tick a held report SHALL be scored with that tick's arousal contrast, gains and goal factor, from its own intensity and its cached novelty.

#### Scenario: Arousal rises while a report is held
- **WHEN** arousal rises between two ticks on which the same report is held
- **THEN** its score on the second tick reflects the second tick's contrast
