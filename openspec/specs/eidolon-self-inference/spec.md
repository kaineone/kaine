# eidolon-self-inference Specification

## Purpose
The self-model module's `SelfInferenceEngine` populates the self-model fields from observed cognitive signals, deriving the personality baseline from the affect module's VAD statistics and the capability map from the effectors module's whitelist and the planning module's outcomes, with an operator-seeded fallback on first boot and no recording of raw speech.
## Requirements
### Requirement: Self-model fields populated from observation
The self-model module's `SelfInferenceEngine` SHALL populate `behavioral_norms`,
`personality_baseline`, `values`, and `capability_map` in `self_model.json` from
observed signals: `language.out` (internal-speech patterns), `affect.report` and
`affect.drive` (VAD trajectories and drive crossings), and `planning.policy` (EFE
outcomes). Fields SHALL be written atomically. A field SHALL remain empty rather
than be populated with speculative data when observations are insufficient
(below `speech_pattern_min_count`).

#### Scenario: Behavioral norms inferred from speech patterns
- **WHEN** the inference engine has observed at least `speech_pattern_min_count`
  internal-speech events matching a consistent pattern
- **THEN** `behavioral_norms` contains the derived pattern entries

#### Scenario: Fields are empty before sufficient observations
- **WHEN** fewer than `speech_pattern_min_count` relevant events have been observed
- **THEN** the corresponding self-model field is empty rather than speculative

### Requirement: Personality baseline from VAD statistics
The `SelfInferenceEngine` SHALL derive `personality_baseline` from rolling mean and
variance of the affect module's valence, arousal, and dominance over `vad_window_cycles`
maintenance cycles. The statistics SHALL be updated atomically on each maintenance
cycle end.

#### Scenario: VAD statistics update on maintenance cycle
- **WHEN** a sleep module maintenance cycle completes
- **THEN** `personality_baseline` reflects the rolling VAD mean and variance over
  the configured window

### Requirement: Capability map from Effectors whitelist and Planning outcomes
The `capability_map` SHALL be built from the effectors module's effector whitelist (what the
entity can execute) combined with the planning module's EFE outcome history (what it has
successfully done). It SHALL be updated on maintenance cycle end.

#### Scenario: Capability map reflects whitelist
- **WHEN** the effectors module's effector whitelist has at least one enabled entry
- **THEN** `capability_map` contains the corresponding capability entries

### Requirement: Operator-seeded first-boot fallback
When `[self_model.self_inference].seed_path` is set, the engine SHALL load the seed
on first boot and use it as the initial state for all four fields. Subsequent
observation-driven updates SHALL be applied on top of the seed. The seed SHALL
NOT be applied automatically if `seed_path` is not configured.

#### Scenario: Seed populates fields before first observation cycle
- **WHEN** `seed_path` is configured and the engine starts for the first time
- **THEN** all four self-model fields reflect the seed values before any
  observation-driven update

#### Scenario: No seed applied without configuration
- **WHEN** `seed_path` is not set
- **THEN** self-model fields start empty and are populated only from observation

### Requirement: Self-inference is operator-opt-in and writes no raw speech
The `SelfInferenceEngine` SHALL be disabled by default (`enabled = false`) and
SHALL NOT write raw internal-speech text to any persistent store. Only counts,
derived norms, and statistical summaries (VAD mean/variance) SHALL be persisted.

#### Scenario: Engine inactive by default
- **WHEN** `[self_model.self_inference].enabled` is false
- **THEN** no observation is recorded and self_model.json fields are not updated
  by this engine

#### Scenario: No raw speech persisted
- **WHEN** the engine processes `language.out` events
- **THEN** no raw text content from those events appears in any written file

