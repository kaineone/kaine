## ADDED Requirements

### Requirement: Two-arm workspace-mediation ablation

The system SHALL provide an ablation runner that executes the cognitive cycle twice
under matched seed, matched stimulus schedule, and matched modules, differing ONLY in
whether the language organ is conditioned by the competitive workspace or by a flat
fan-in of the same module outputs. The workspace-on arm SHALL use Syneidesis
competitive selection and broadcast as built. The workspace-off arm SHALL bypass
scoring, threshold, top-k selection, inhibition, and broadcast, and condition the organ
on a flat rendering of all current module outputs. The runner SHALL reuse the
deterministic offline harness pattern (in-memory scripted bus, `deterministic=True`).

#### Scenario: Arms differ only in workspace mediation

- **WHEN** the runner executes the workspace-on and workspace-off arms
- **THEN** both arms use the same seed, the same scripted stimulus, and the same
  registered modules, and the only difference is whether the organ is conditioned by
  the competitively-selected coalition or by a flat rendering of the same module
  outputs

#### Scenario: No module internals are modified

- **WHEN** the ablation runs
- **THEN** Soma, Chronos, Syneidesis, Volition, and Lingua execute their shipped
  behavior unchanged, and the workspace-off arm is realized purely in the conditioning
  path (which snapshot is handed to the context assembler), not by altering any module

### Requirement: Fair-null rendering discipline

The workspace-off arm SHALL give the language organ the SAME underlying information as
the workspace-on arm — the module outputs — differing only in structure (competitively
selected coalition vs. flat concatenation). The rendering budget (max events, char
budget) SHALL be matched across arms so that any divergence is attributable to
selection structure and not to information quantity. In the off arm the modules SHALL
keep their forward models, keep predicting from their own signals, and keep publishing
real prediction errors; they SHALL NOT be starved, silenced, or fed constants.

#### Scenario: Rendering budget matched across arms

- **WHEN** each arm renders its conditioning context for the organ
- **THEN** both arms use the same max-events and char-budget bounds, so the off arm is
  not starved and the on arm is not advantaged by information quantity

#### Scenario: Off-arm modules remain non-degenerate

- **WHEN** the workspace-off arm runs
- **THEN** each module still runs its forward model and publishes a real prediction
  error that varies with its own input, so a NULL reflects an inert workspace rather
  than a degenerate control

### Requirement: Competition capacity in the minimal set

The minimal-set ablation SHALL be configured so that competitive selection genuinely
competes rather than admitting every candidate, since selection only excludes when the
candidate count exceeds workspace capacity. The runner SHALL either set the
workspace `top_k` below the number of concurrent candidates, or drive a stimulus that
produces more concurrent candidates than `top_k`, and SHALL record which regime was
used. When capacity is not exceeded, the runner SHALL report that the run tests
broadcast-mediation-plus-gating rather than competitive selection, so a WIN is not
overclaimed as evidence for competition.

#### Scenario: Selection actually excludes

- **WHEN** the minimal-set ablation runs in the competition regime
- **THEN** the number of candidates per tick exceeds `top_k` on a reported fraction of
  ticks, so the workspace-on arm excludes candidates the workspace-off arm would have
  passed to the organ

#### Scenario: Non-competing regime is disclosed, not hidden

- **WHEN** candidate count does not exceed `top_k` for a run
- **THEN** the runner records that the run exercises broadcast mediation and gating but
  not competitive exclusion, and the verdict text scopes the claim accordingly

### Requirement: Primary and secondary measures

The runner SHALL treat per-module error-trajectory structure and coalition-selection
structure as the PRIMARY evidence, and language-organ output divergence as SECONDARY
confirmation. All measures SHALL be computed across multiple seeds with greedy
(temperature-0) decoding so the observable carries no sampling noise.

#### Scenario: Primary measure 1 — cross-module error coupling

- **WHEN** the runner analyzes per-module precision-weighted error time series
- **THEN** it computes the Pearson correlation between Soma's and Chronos's error series
  over a sliding window for each arm, and the pre-registered directional criterion is a
  statistically significant INCREASE in that correlation under workspace-on relative to
  workspace-off (reflecting mutual influence via the shared broadcast); if the on-arm
  coupling is not greater than the off-arm coupling, the workspace is judged inert on
  this measure

#### Scenario: Primary measure 2 — coalition-selection structure

- **WHEN** the runner analyzes the on-arm coalition sequence
- **THEN** it computes the Shannon entropy of the coalition-source distribution over a
  window (which must fall between uniform and degenerate), and tests whether the
  structured selection yields different downstream behavior than flat fan-in

#### Scenario: Secondary measure — output divergence confirms propagation

- **WHEN** the runner measures organ output divergence (cosine distance of greedy-
  decoded response embeddings between arms)
- **THEN** it is reported as secondary confirmation that the primary effects propagate
  to the observable, and NOT as independent evidence that the workspace does work

### Requirement: Soma-salience coverage for measure power

The ablation's stimulus battery SHALL include substrate perturbations that make Soma's
prediction error salient on a reported fraction of ticks, because cross-module coupling
can only be detected when Soma periodically enters the selected coalition. A run in
which Soma never enters the coalition SHALL be flagged as underpowered for the primary
coupling measure rather than reported as a clean NULL.

#### Scenario: Battery exercises Soma salience

- **WHEN** the ablation battery runs
- **THEN** Soma's error crosses into the selected coalition on a reported fraction of
  ticks, so the coupling path from Soma through the broadcast to Chronos is exercised

#### Scenario: Underpowered run is flagged, not counted as NULL

- **WHEN** Soma never enters the coalition across a run
- **THEN** the run is flagged underpowered for primary measure 1 rather than reported
  as a NULL, so a false NULL from flat substrate is not mistaken for an inert workspace

### Requirement: Reachable adverse verdict

The runner SHALL classify the outcome as WIN, NULL, or NEGATIVE using the shared
verdict vocabulary, with real non-zero minimum-effect thresholds and at least one
non-engineered (neutral) stimulus battery, so that a NULL (workspace mediation makes no
measurable difference — the system is a prompt-assembler) and a NEGATIVE (mediation
makes a difference adverse to the thesis) are both genuinely reachable through the real
pipeline, not a wiring test wired to always win.

#### Scenario: Indistinguishable arms yield NULL

- **WHEN** the workspace-on and workspace-off arms produce error-coupling and selection
  structure whose divergence is at or below the minimum-effect threshold
- **THEN** the runner returns NULL and reports it as a null (the architecture is a
  fan-in prompt-assembler), not as a win

#### Scenario: Neutral battery available

- **WHEN** the ablation is run
- **THEN** a neutral, non-engineered stimulus battery is selectable alongside positive
  and negative controls, and the verdict is not forced by a stimulus constructed to
  guarantee divergence

### Requirement: Scoped reproducibility and multiple-comparisons correction

Seed-reproducibility SHALL be claimed only for the offline/deterministic runner (same
seed reproduces verdict and metrics), NOT for the live temperature-driven organ cycle.
When reported alongside other verdict-producing experiments, a family-wise multiple-
comparisons correction SHALL be applied across the primary measures and both raw and
corrected verdicts reported.

#### Scenario: Offline run reproduces from its seed

- **WHEN** the offline runner is executed twice with the same seed
- **THEN** it produces identical verdict and identical metrics

#### Scenario: Divergence proves work, not superiority

- **WHEN** the runner reports a WIN
- **THEN** the report states the WIN establishes that workspace mediation does
  measurable work, and does NOT by itself claim the workspace produces more coherent or
  better output (which requires an added coherence measure), nor that it beats every
  possible aggregation strategy beyond the flat fan-in control
