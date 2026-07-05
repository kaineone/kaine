## ADDED Requirements

### Requirement: Memory probe scoring uses async-only path
`kaine/evaluation/memory_probes.py` SHALL expose exactly one
reconstruction scorer, `score_async(response, memory, embedder)`,
and SHALL NOT carry a synchronous placeholder that returns a
constant. `MemoryProbeRunner.run_once` MUST call `score_async`
when computing reconstruction accuracy.

#### Scenario: No synchronous stub present
- **WHEN** an operator runs `git grep "reconstruction_accuracy" kaine/`
- **THEN** the search returns no matches

#### Scenario: Runner uses async scorer
- **WHEN** `MemoryProbeRunner.run_once` produces a probe sample
- **THEN** the `accuracy` field is the float returned by
  `score_async`, not a constant `0.0`
