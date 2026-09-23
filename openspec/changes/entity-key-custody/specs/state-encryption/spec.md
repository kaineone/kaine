## ADDED Requirements

### Requirement: Cognitive state is encrypted under per-entity keys
After migration, persisted cognitive state SHALL be encrypted under the owning entity's data key as defined by `entity-key-custody`, and the operator-held key sources (`KAINE_STATE_KEY`, the kernel keyring entry and `secrets/state_key`) SHALL be accepted only by the one-way migration tool.

#### Scenario: Operator key after migration
- **WHEN** a migrated host boots with `KAINE_STATE_KEY` set
- **THEN** the runtime ignores it for entity state and logs that per-entity custody is active
