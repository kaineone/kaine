## ADDED Requirements

### Requirement: The seed is preserved only with its maturation reference
When a step's resolved configuration enables the individuation producer, the study runner SHALL request the developmental phase's maturation preservation only after the cycle reports the individuation maturation reference complete, or after a bounded wait has run out. The reference and its ledger are encrypted, so the runner SHALL read only the content-free `individuation` block of the child's `state/cycle/runtime.json`, which carries the reference kind and whether the reference and its ledger are both saved; it is complete when the kind is `maturation` and both are saved. The runner SHALL NOT read the individuation store. When the wait runs out the runner SHALL preserve the entity before it stops it, SHALL record the step with the outcome `failed:maturation_reference_missing`, and SHALL halt the study.

#### Scenario: The reference arrives after the bloom ends
- **WHEN** the maturation bloom has ended and the reference and ledger appear later within the bound
- **THEN** the maturation preservation is requested after they appear and the step completes with `maturation_reference` `complete`

#### Scenario: The reference never arrives
- **WHEN** the reference or its ledger is still missing when the bound runs out
- **THEN** the entity is preserved, the step is recorded as `failed:maturation_reference_missing` and the study halts

#### Scenario: The reference is already present
- **WHEN** the reference and ledger exist when the maturation bloom ends
- **THEN** the maturation preservation is requested without waiting

#### Scenario: A capture reference does not count
- **WHEN** the runtime block reports a complete reference of kind `capture`
- **THEN** the runner keeps waiting for a maturation reference

#### Scenario: The runner never reads the encrypted reference
- **WHEN** the reference and ledger on disk are ciphertext
- **THEN** the wait still releases on the runtime block alone
