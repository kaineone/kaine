## ADDED Requirements

### Requirement: The identity holds the entity's launch name
`EntityIdentity` SHALL hold an optional `name`, stored in `state/identity/entity.json` under `"name"` only when it is set, so an identity without a name serializes byte-identically to the format before names. Loading SHALL accept an identity file with or without `name`. Before any module starts, the cycle SHALL give the entity a name if its identity has none: the self-model document's name when it has one, otherwise "Kaine <Surname>" with the surname drawn from `kaine/modules/self_model/surnames.txt`. A revived identity SHALL keep the bundle's name. When the bundle identity has no name, the name SHALL be, in order: the name of the self-model state the bundle captured (used only when the bundle holds that state); the name stored in the target tree for the same `entity_id`; a newly drawn name. A name stored under a different `entity_id`, and a name in the target tree's own self-model document, SHALL NOT be adopted on a revive. During a revive of an unnamed bundle identity the self-model SHALL neither mint nor keep a name nor write its document until the final name is decided. A stored name SHALL be replaced only when the new name comes from the bundle itself. Saving SHALL refuse to replace a stored name with a different one, except that a revive may replace the stored name of the same `entity_id` with the bundle's name through an explicit option that logs a warning naming both names. A fork SHALL receive a newly drawn name that differs from its parent's (and, for an unnamed parent, from the name in the parent's captured self-model state), and the parent's name SHALL NOT be copied into the fork's own `name`. The identity MAY hold an optional `lineage_names` map from ancestor `entity_id` to name, written only when non-empty, to which a fork adds its named parent and keeps the earlier entries; plaintext sidecars and manifests keep `entity_id` and `lineage` only. Names SHALL be valid as defined below. Saving and naming SHALL hold an exclusive lock beside the identity file and write through a temp file unique to the writer, so concurrent first boots agree on one identity and one name. Preservation bundles and decommission backups SHALL carry the name with the identity.

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

#### Scenario: A revive names a nameless bundle
- **WHEN** a bundle identity without a name is revived into a tree whose identity has the same `entity_id` and the name "Kaine Aurora", and the revived self-model state is named "Kaine Nova"
- **THEN** the identity file's `name` becomes "Kaine Nova", and the running self-model keeps it

#### Scenario: A revive keeps the bundle's name
- **WHEN** a bundle named "Kaine Nova" is revived into a tree whose identity has the same `entity_id` and the name "Kaine Aurora"
- **THEN** the identity file's `name` becomes "Kaine Nova" and a warning names both names

#### Scenario: An unreadable self-model document defers naming
- **WHEN** the cycle starts on a tree whose identity file has no name and whose self-model document exists but cannot be read
- **THEN** a warning is logged, no name is saved this boot, and the next boot tries again; a name is minted only when the document is absent or readable with no name

#### Scenario: Name validity
- **WHEN** a name is empty, has leading or trailing whitespace, spans several lines, exceeds 64 characters, or contains a character in any Unicode "C" category (controls, bidi and other format characters)
- **THEN** it is rejected as an identity name and counts as no name when read from a self-model document

#### Scenario: A revive without captured self-model state
- **WHEN** an unnamed bundle identity is revived into a tree whose identity has the same `entity_id` and the name "Kaine Aurora", and the bundle holds no self-model state
- **THEN** the identity file keeps "Kaine Aurora" and the running self-model adopts it

#### Scenario: A foreign document is not adopted on a revive
- **WHEN** an unnamed bundle identity is revived into a tree with no identity file whose self-model document is named "Kaine Other"
- **THEN** the identity takes a newly drawn name, not "Kaine Other"

#### Scenario: Lineage names
- **WHEN** an entity named "Kaine Nova" is forked, and the fork is forked again
- **THEN** the second fork's identity lists "Kaine Nova" and the first fork's name under their `entity_id` values in `lineage_names`, and its own name differs from its parent's

#### Scenario: Concurrent first boots
- **WHEN** several boots start at once on a fresh state tree
- **THEN** they return one `entity_id` and one name, and no temp file remains

#### Scenario: A deferred naming is reported
- **WHEN** boot defers naming because the self-model document cannot be read
- **THEN** a health-surface warning is recorded and an operator event `identity.naming_deferred` is published on the housekeeping stream, on every boot that defers
