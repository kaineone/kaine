## ADDED Requirements

### Requirement: The workspace runs one arm of the planned ablation
The workspace SHALL run one of three arms, selected by `[syneidesis].arm`: `competitive` (the default), `matched` or `pooled` (paper §6.3, A.8). In the competitive arm selection, access and inhibition SHALL be as before. Every snapshot SHALL carry its arm in `metadata["arm"]`. The matched and pooled arms SHALL be refused when the coherence layer is on, and an unknown arm SHALL be refused. The `[syneidesis]` key guard SHALL accept `arm`, so the shipped configuration boots.

#### Scenario: The default arm is competitive
- **WHEN** the workspace is built without an arm
- **THEN** its snapshots equal those of the competitive arm and carry `metadata["arm"] == "competitive"`

#### Scenario: An unknown arm is refused
- **WHEN** the workspace is built with arm `"random"`
- **THEN** construction raises `ValueError`

### Requirement: The matched arm draws a score-blind coalition of the competitive size
In the matched arm, on a broadcast tick, the workspace SHALL score every candidate as in the competitive arm and SHALL draw `min(top_k, n)` of the `n` candidates uniformly without replacement, without regard to score, from a generator seeded from the run seed. The drawn members SHALL be ordered by score, descending. A drawn member SHALL be accessed when its score reaches the access threshold, and the snapshot SHALL be inhibited when no drawn member is accessed. The score table SHALL hold every candidate's score. A tick that is not a broadcast tick SHALL draw nothing, and a context that does not say whether the tick is a broadcast tick SHALL be refused rather than fall back to top-k selection. The generator's state SHALL NOT be persisted: the draws are reproducible within one uninterrupted run, and a restart or revive starts the stream again from the seed.

#### Scenario: The matched coalition has the competitive size
- **WHEN** a broadcast tick has 12 candidates and `top_k=5`
- **THEN** the matched coalition has 5 members, as the competitive coalition does

#### Scenario: The same seed reproduces the draws
- **WHEN** two matched runs with the same seed see the same broadcast ticks
- **THEN** they draw the same coalitions

#### Scenario: A matched selection without the broadcast flag is refused
- **WHEN** a matched `select` is called with a context that has no `is_experiential` key
- **THEN** it raises `ValueError`

#### Scenario: Access follows the threshold within the draw
- **WHEN** the best candidate scores 0.9, the threshold is 0.35, and every drawn member scores below 0.35
- **THEN** the snapshot is inhibited

### Requirement: The pooled arm broadcasts every candidate with no gate
In the pooled arm the workspace SHALL score no candidate. Every candidate of the tick SHALL be a member, in the tick's canonical order; the snapshot SHALL NOT be inhibited, even with no candidates; the score table SHALL carry each candidate's intensity in place of a score; and the metadata SHALL carry no access threshold.

#### Scenario: Every candidate is a member
- **WHEN** a pooled tick has 12 candidates and `top_k=5`
- **THEN** the snapshot has all 12 as members, is not inhibited, and scores each with its intensity

### Requirement: A pooled broadcast always replaces the context
A processor's broadcast context SHALL adopt every pooled broadcast with all its members, whatever their intensity, and an empty pooled broadcast SHALL replace the context with the featurization of the empty set. In the other arms a broadcast with no accessed member SHALL leave the context unchanged.

#### Scenario: A pooled member below the competitive threshold enters the context
- **WHEN** a pooled broadcast carries a member of intensity 0.1
- **THEN** that member's intensity enters the context

#### Scenario: An empty pooled broadcast replaces the context
- **WHEN** a processor holds a context and receives an empty pooled broadcast
- **THEN** its context becomes the featurization of the empty set

#### Scenario: The shipped configuration boots
- **WHEN** the shipped configuration with the `thesis_test` profile passes through the boot phase that builds the workspace
- **THEN** the key guard accepts `[syneidesis].arm` and the workspace runs the competitive arm
