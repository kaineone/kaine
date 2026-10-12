## MODIFIED Requirements

### Requirement: Agent profile fork/merge persistence
Social cognition SHALL implement `serialize()` / `deserialize()` on `AgentStore`, and the lifecycle layer SHALL provide an `EmpatheiaMergeStrategy` (beside `MnemosMergeStrategy` in `kaine.lifecycle.strategies`) that `default_strategies()` registers under `"empatheia"`, so that agent profiles survive the fork/merge cycle. On merge, the strategy MUST reconcile two diverged profile sets: interaction counts are summed, histograms, behavioural summaries and reliability are averaged with interaction count as the weight, `first_seen` takes the earlier and `last_seen` the later value. A behavioural-summary entry that is missing or null on one side is absent, not 0: an entry defined on both sides takes the count-weighted average, an entry defined on one side takes that side's value, an entry defined on neither side stays absent, and when the sides that hold a value have no interactions their plain mean is used. The merged profiles SHALL be carried in the merged snapshot; restoring that snapshot loads them into the store, which serves them before any Qdrant copy and writes each to Qdrant on its next update.

#### Scenario: Fork/merge round-trip preserves interaction count
- **WHEN** an agent profile is updated in a forked instance and the fork is merged
  back
- **THEN** the merged agent profile has an interaction count at least as large as
  the maximum of the two forked counts

#### Scenario: ForkManager uses the Social cognition strategy by default
- **WHEN** `ForkManager.merge` combines two snapshots whose `empatheia` state holds the same agent with interaction counts 5 and 3
- **THEN** the merged snapshot's profile for that agent has interaction count 8

#### Scenario: Serialize/deserialize round-trip is lossless
- **WHEN** an `AgentStore` is serialized and deserialized
- **THEN** every agent profile (id, histogram, interaction_count, familiarity) is
  recovered without loss

#### Scenario: A fork without a defined error does not pull the average toward 0
- **WHEN** two forks of the same agent are merged and only one holds a `mean_prediction_error`, of 0.6, while the other's is missing or null
- **THEN** the merged profile's `mean_prediction_error` is 0.6, and when neither fork holds one the merged profile has none
