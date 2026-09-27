## ADDED Requirements

### Requirement: Chronos's reservoir survives preservation and needs no torch
Chronos's CfC reservoir SHALL be generated from a seed drawn once when Chronos is first created, from the process's ambient NumPy random state unless the caller supplies one, so a run seeded through the experiment seeding helper rebuilds the same reservoir while an unseeded process gets a fresh one; the seed SHALL be part of its serialized state, and a revived Chronos SHALL rebuild the identical reservoir from it before restoring its prediction head. A snapshot without a seed SHALL start a new reservoir and say so in the log. Chronos SHALL offer a NumPy CfC backend, the default, that needs no torch and matches the torch backend to 1e-5 given the same weights; the parameter count and the CPU-only policy are unchanged.

#### Scenario: A seeded experiment reproduces
- **WHEN** two Chronos instances are created after the same `set_global_seed` call and given no reservoir seed
- **THEN** they draw the same reservoir seed and produce the same outputs

#### Scenario: Revive keeps the reservoir
- **WHEN** Chronos is preserved and revived in a new process
- **THEN** the same workspace inputs give the same hidden states as before preservation

#### Scenario: An older snapshot
- **WHEN** Chronos is restored from a snapshot without a reservoir seed
- **THEN** it keeps a new reservoir and logs that the reservoir is new
