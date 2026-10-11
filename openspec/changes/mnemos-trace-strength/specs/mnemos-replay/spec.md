## MODIFIED Requirements

### Requirement: Affect/recency replay selection
Mnemos SHALL select replay traces by a score combining affect intensity and
recency (`affect_weight × intensity + recency_weight × recency`), returning the
top `selection_top_k` traces. The candidates SHALL be every persisted trace
stored since the previous downscaling (`born_sleep` equal to the sleep count),
including those persisted by eviction during the wake, plus any short-term
entry. Recency SHALL map each candidate's `entity_time` linearly onto [0, 1]
across the candidates. Each replayed trace SHALL name its point id and its
collection.

#### Scenario: Emotionally significant, recent traces rank first
- **WHEN** the replay selector ranks a set of traces
- **THEN** a high-intensity recent trace ranks above a low-intensity old one

#### Scenario: An evicted trace of the wake can be replayed
- **WHEN** a high-arousal trace stored early in a wake was persisted by eviction
  before the sleep
- **THEN** the sleep's replay selects it

#### Scenario: Earlier wakes are not in the pool
- **WHEN** a sleep replays
- **THEN** no trace stored before the previous sleep is a candidate
