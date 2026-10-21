## ADDED Requirements

### Requirement: The identity holds the entity's launch name
`EntityIdentity` SHALL hold an optional `name`, stored in `state/identity/entity.json` under `"name"` only when it is set, so an identity without a name serializes byte-identically to the format before names. Loading SHALL accept an identity file with or without `name`. Before any module starts, the cycle SHALL give the entity a name if its identity has none: the self-model document's name when it has one, otherwise "Kaine <Surname>" with the surname drawn from `kaine/modules/self_model/surnames.txt`. A revived identity SHALL keep the bundle's name. Saving SHALL refuse to replace a stored name with a different one. A fork SHALL receive a newly drawn name that differs from its parent's, and the parent's name SHALL NOT be copied into the fork's identity. Preservation bundles and decommission backups SHALL carry the name with the identity.

#### Scenario: A fresh spawn is named
- **WHEN** the cycle starts on a fresh state tree with the self-model module disabled
- **THEN** `state/identity/entity.json` holds a `name` of the form "Kaine <Surname>"

#### Scenario: An unnamed identity adopts the self-model's name
- **WHEN** the cycle starts on a tree whose identity file has no name and whose self-model document is named "Kaine Nova"
- **THEN** the identity file's `name` becomes "Kaine Nova"

#### Scenario: Old files are unchanged
- **WHEN** an identity without a name is saved
- **THEN** the file's bytes equal those written before names existed

#### Scenario: A fork's name
- **WHEN** an entity named "Kaine Nova" is forked
- **THEN** the fork's identity has a different name and the lineage names the parent's `entity_id`

#### Scenario: No overwrite
- **WHEN** an identity named "Kaine Nova" is saved over with a different name
- **THEN** saving raises an error and the file is unchanged
