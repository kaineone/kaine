## MODIFIED Requirements

### Requirement: Agent profile fork/merge persistence
Empatheia SHALL implement `serialize()` / `deserialize()` on `AgentStore`, and the lifecycle layer SHALL provide an `EmpatheiaMergeStrategy` (beside `MnemosMergeStrategy` in `kaine.lifecycle.strategies`) that `default_strategies()` registers under `"empatheia"`, so that agent profiles survive the fork/merge cycle. On merge, the strategy MUST reconcile two diverged profile sets: interaction counts are summed, histograms, behavioural summaries and reliability are averaged with interaction count as the weight, `first_seen` takes the earlier and `last_seen` the later value. The merged profiles SHALL be carried in the merged snapshot; restoring that snapshot loads them into the store, which serves them before any Qdrant copy and writes each to Qdrant on its next update.

#### Scenario: Fork/merge round-trip preserves interaction count
- **WHEN** an agent profile is updated in a forked instance and the fork is merged
  back
- **THEN** the merged agent profile has an interaction count at least as large as
  the maximum of the two forked counts

#### Scenario: ForkManager uses the Empatheia strategy by default
- **WHEN** `ForkManager.merge` combines two snapshots whose `empatheia` state holds the same agent with interaction counts 5 and 3
- **THEN** the merged snapshot's profile for that agent has interaction count 8

#### Scenario: Serialize/deserialize round-trip is lossless
- **WHEN** an `AgentStore` is serialized and deserialized
- **THEN** every agent profile (id, histogram, interaction_count, familiarity) is
  recovered without loss
