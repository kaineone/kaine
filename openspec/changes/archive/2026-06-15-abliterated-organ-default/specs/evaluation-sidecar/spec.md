## ADDED Requirements

### Requirement: A/B-divergence baseline uses the language organ's model

The evaluation A/B-divergence baseline SHALL run the same model as the language
organ. `[evaluation].chat_model_id` SHALL derive from `[lingua].model_id` when not
explicitly set, and SHALL fail closed when explicitly set to a different value:
the cycle SHALL refuse to boot with a clear operator message naming both values,
before any resource (bus, modules, runtime state) is opened. This holds because
the baseline runs bare (no architecture), so a differing baseline model would make
the divergence measure a model difference instead of the architecture's
conditioning.

#### Scenario: Baseline derives from the organ when unset

- **WHEN** `[evaluation].chat_model_id` is absent
- **THEN** the A/B baseline uses `[lingua].model_id`

#### Scenario: Explicit matching value is accepted

- **WHEN** `[evaluation].chat_model_id` equals `[lingua].model_id`
- **THEN** the configuration loads normally

#### Scenario: Explicit divergent value fails closed

- **WHEN** `[evaluation].chat_model_id` is set to a value different from
  `[lingua].model_id`
- **THEN** the cycle refuses to boot with a clear error naming both values
- **AND** no bus connection, module, or runtime state file has been created
