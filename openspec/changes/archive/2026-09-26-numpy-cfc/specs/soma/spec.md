## ADDED Requirements

### Requirement: Soma's reservoir survives preservation and needs no torch
Soma's CfC reservoir SHALL be generated from a seed drawn once when Soma is first created, from the process's ambient NumPy random state unless the caller supplies one, so a run seeded through the experiment seeding helper rebuilds the same reservoir while an unseeded process gets a fresh one; the seed SHALL be part of its serialized state, and a revived Soma SHALL rebuild the identical reservoir from it before restoring its readout. A snapshot without a seed SHALL start a new reservoir and say so in the log. Soma SHALL offer a NumPy CfC backend, the default, that needs no torch and matches the torch backend to 1e-5 given the same weights.

#### Scenario: A seeded experiment reproduces
- **WHEN** two Soma instances are created after the same `set_global_seed` call and given no reservoir seed
- **THEN** they draw the same reservoir seed and produce the same outputs

#### Scenario: Revive keeps the reservoir
- **WHEN** Soma is preserved and revived in a new process
- **THEN** its reservoir weights are identical to the preserved ones, and the same inputs give the same hidden states and predictions

#### Scenario: A host without torch
- **WHEN** Soma runs on the NumPy backend where torch cannot be imported
- **THEN** it starts and runs, and the extras check does not require the `core` extra for it
