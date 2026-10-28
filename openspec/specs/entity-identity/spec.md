# entity-identity Specification

## Purpose
This capability gives each entity one persistent, opaque identity and lineage that survives restarts, forks, preservation and revival, so every lifecycle decision can tell which entity it concerns and whether it has lived before.

## Requirements

### Requirement: An entity has one persistent identity
KAINE SHALL give each entity one `EntityIdentity`, holding an opaque `entity_id`, its ancestors' IDs as `lineage` (oldest first), an `origin` of `minted` or `legacy`, and, for a legacy identity, its `legacy_source`. The identity SHALL be persisted in the entity's state tree, written atomically and owner-only. Saving SHALL refuse to replace an identity file that holds a different `entity_id`.

#### Scenario: Round-trip
- **WHEN** an identity is saved and loaded again
- **THEN** the loaded identity equals the saved one

#### Scenario: Refuse to overwrite another entity
- **WHEN** an identity is saved to a path holding a different `entity_id`
- **THEN** saving raises an error and the file is unchanged

### Requirement: An identity is minted only at a fresh spawn
The cycle SHALL mint a new identity only when the state tree has no identity file and none of its own lived artifacts: the developmental stage file, the world-model checkpoint, the sleep module's consolidation-divergence record and the perception desired-state. Fork snapshots and preservation bundles under the state tree SHALL NOT count as the tree's own lived artifacts. A state tree with own lived artifacts but no identity file SHALL receive a legacy identity derived deterministically from those artifacts, persisted at once. Revival, restart and merge SHALL NOT mint.

#### Scenario: Fresh spawn
- **WHEN** the cycle starts on a state tree with no identity file and no prior lived history
- **THEN** a minted identity with empty lineage is saved

#### Scenario: Lived tree without an identity
- **WHEN** the cycle starts on a state tree with a checkpoint from the world model module and no identity file
- **THEN** a legacy identity is saved, and starting again yields the same `entity_id`

#### Scenario: Fresh spawn beside other entities
- **WHEN** the cycle starts on a state tree with no identity file and none of its own lived artifacts, while `state/forks` and `state/preservation` hold other entities' snapshots and bundles
- **THEN** a minted identity is saved and the entity resolves to the developmental phase

### Requirement: Snapshots carry the identity and forks record lineage
Fork and preservation snapshots SHALL record the entity's identity in their metadata. A fork SHALL receive a newly minted `entity_id` whose lineage is the parent's lineage followed by the parent's `entity_id`. A merge SHALL keep the target entity's identity and record the merged-in entity's `entity_id` as `merged_from_entity`.

#### Scenario: Fork lineage
- **WHEN** an entity with lineage `[a]` and ID `b` is forked
- **THEN** the fork's identity has a new ID and lineage `[a, b]`

### Requirement: Revival restores identity and never mints
Revival SHALL restore the identity recorded in the bundle. A bundle without an identity SHALL revive with a legacy identity derived from its preservation ID, so that reviving the same bundle twice yields the same `entity_id`. Revival SHALL refuse when the target state tree already holds a different identity.

#### Scenario: Legacy bundle
- **WHEN** a bundle written before identities existed is revived twice into fresh trees
- **THEN** both revivals record the same legacy `entity_id`

#### Scenario: Conflict
- **WHEN** a bundle is revived into a tree whose identity file holds a different `entity_id`
- **THEN** revival raises an error and changes nothing

### Requirement: Prior history is scoped to the entity's lineage
The lineage-scoped history query SHALL report prior lived history when any fork snapshot or preservation record carries the entity's `entity_id` or an ID in its lineage, reading metadata and manifests only. Records belonging to other entities, and records without an identity, SHALL NOT count for an entity with a known identity. An entity whose identity cannot be determined SHALL count as having lived.

#### Scenario: Another entity's bundle
- **WHEN** the state tree holds a preservation bundle of a different entity and nothing of this entity's lineage
- **THEN** the query reports no prior history

#### Scenario: Unknown identity
- **WHEN** the query is asked about an entity with no determinable identity
- **THEN** it reports prior history

### Requirement: The identity is readable without decryption
Every encrypted container of an entity's state SHALL have a plaintext identity record beside it holding the entity's `entity_id` and `lineage`: a fork snapshot's `identity.json`, a preservation bundle's and a decommission backup's `manifest.json`, and a forked-entity job's payload. Reading it SHALL NOT require decryption. When the container is opened, the in-container identity SHALL agree with the plaintext record, or loading SHALL fail.

#### Scenario: Sidecar without decryption
- **WHEN** an entity's fork snapshot is saved with state encryption enabled
- **THEN** its directory holds a plaintext `identity.json` with the entity's `entity_id` and `lineage`

#### Scenario: Disagreement fails
- **WHEN** a snapshot's plaintext identity record names a different `entity_id` from the identity inside the snapshot
- **THEN** loading raises an identity error

### Requirement: The identity format and legacy derivation are frozen
An `entity_id` SHALL be `ent-` or `legacy-` followed by 32 lowercase hexadecimal characters. A legacy ID SHALL be `legacy-` followed by the first 32 hexadecimal characters of the SHA-256 of its UTF-8 source string. The sources SHALL be `bundle:<preservation_id>`, and `tree:` followed by the SHA-256 hex of the newline-joined, sorted lines `<path relative to the state root>\0<SHA-256 hex of the file>` for each of the tree's own lived artifacts.

#### Scenario: Golden value
- **WHEN** the legacy identity of source `bundle:abc` is derived
- **THEN** its `entity_id` is `legacy-` followed by the first 32 hex characters of SHA-256 of `bundle:abc`

### Requirement: The identity holds the entity's launch name
`EntityIdentity` SHALL hold an optional `name`, stored in `state/identity/entity.json` under `"name"` only when it is set, so an identity without a name serializes byte-identically to the format before names. Loading SHALL accept an identity file with or without `name`. Before any module starts, the cycle SHALL give the entity a name if its identity has none: the self-model document's name when it has one, otherwise "Kaine <Surname>" with the surname drawn from `kaine/modules/self_model/surnames.txt`. A revived identity SHALL keep the bundle's name. When the bundle identity has no name, the name SHALL be, in order: the name of the self-model state the bundle captured (used only when the bundle holds that state); the name stored in the target tree for the same `entity_id`; a newly drawn name. A name stored under a different `entity_id`, and a name in the target tree's own self-model document, SHALL NOT be adopted on a revive. During a revive of an unnamed bundle identity the self-model SHALL neither mint nor keep a name nor write its document until the final name is decided. A stored name SHALL be replaced only when the new name comes from the bundle itself. Saving SHALL refuse to replace a stored name with a different one, except that a revive may replace the stored name of the same `entity_id` with the bundle's name through an explicit option that logs a warning naming both names. A fork SHALL receive a newly drawn name that differs from its parent's and from every name in its parent's `lineage_names` (and, for an unnamed parent, from the name in the parent's captured self-model state), and the parent's name SHALL NOT be copied into the fork's own `name`. The identity MAY hold an optional `lineage_names`, stored as an ordered list of `[entity_id, name]` pairs in lineage order (ids unique and in lineage order, names valid), written only when non-empty, to which a fork adds its parent (by name, or for an unnamed parent by the name in its captured self-model state) and keeps the earlier entries; decommission covers the lock file `entity.json.lock` beside the identity file; plaintext sidecars and manifests keep `entity_id` and `lineage` only. Names SHALL be valid as defined below. Saving and naming SHALL hold an exclusive lock beside the identity file and write through a temp file unique to the writer, so concurrent first boots agree on one identity and one name. Preservation bundles and decommission backups SHALL carry the name with the identity.

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
- **THEN** the second fork's identity lists "Kaine Nova" and the first fork's name under their `entity_id` values in `lineage_names`, and its own name differs from its parent's and its grandparent's

#### Scenario: Concurrent first boots
- **WHEN** several boots start at once on a fresh state tree
- **THEN** they return one `entity_id` and one name, and no temp file remains

#### Scenario: A deferred naming is reported
- **WHEN** boot defers naming because the self-model document cannot be read
- **THEN** a health-surface warning is recorded and an operator event `identity.naming_deferred` is published on the housekeeping stream, on every boot that defers
