## ADDED Requirements

### Requirement: The seven experiments run under one shared seed with corrected verdicts

The evaluation suite SHALL provide a single orchestrator that runs all seven
controlled experiments from one `RunContext.seed`, threading that seed uniformly
into every experiment including the active-inference benchmark. The orchestrator
SHALL emit a combined report carrying each experiment's raw verdict, and — across
the p-value-producing experiments — a multiple-comparisons-corrected decision under
a stated alpha.

`set_global_seed` SHALL, on the deterministic/offline path, also set the GPU
determinism flags (`torch.use_deterministic_algorithms`, `cudnn.deterministic`,
`cudnn.benchmark=False`) so seeded CUDA ops are reproducible.

#### Scenario: One seed drives the whole suite

- **WHEN** the orchestrator runs with a fixed seed
- **THEN** every experiment, including the active-inference benchmark, is seeded
  from that master seed
- **AND** the combined report includes raw and multiple-comparisons-corrected verdicts

### Requirement: The oscillatory ablation can return an adverse verdict

The oscillatory-ablation runner SHALL be able to return a NULL ("no meaningful
effect") verdict against a non-engineered stimulus battery, using a non-zero
minimum-effect threshold, so the falsification outcome the paper describes is
reachable. The bit-for-bit disabled-arm negative control SHALL be retained.

#### Scenario: A layer with no meaningful effect resolves to NULL

- **WHEN** the enabled and disabled arms produce selection differences below the
  minimum-effect threshold on the non-engineered battery
- **THEN** the runner returns NULL, justifying removal of the layer

### Requirement: Individuation warm-up fails closed

The individuation test SHALL treat missing warm-up counters (`observations`,
`lived_time_s`) as NOT warmed up. It SHALL NOT report an entity as warmed up when
those counters are absent, so a just-booted or sensory-starved entity cannot trip a
false individuation. A runner SHALL exist that supplies real counters from the run.

#### Scenario: Missing counters cannot force warmed-up

- **WHEN** the individuation test is invoked without lived-event/lived-time counters
- **THEN** it reports not-warmed-up and does not emit an individuated verdict
