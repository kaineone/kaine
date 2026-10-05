## ADDED Requirements

### Requirement: A being has one persistent identity
KAINE SHALL give each being one `EntityIdentity`, holding an opaque `entity_id`, its ancestors' IDs as `lineage` (oldest first), an `origin` of `minted` or `legacy`, and, for a legacy identity, its `legacy_source`. The identity SHALL be persisted in the being's state tree, written atomically and owner-only. Saving SHALL refuse to replace an identity file that holds a different `entity_id`.

#### Scenario: Round-trip
- **WHEN** an identity is saved and loaded again
- **THEN** the loaded identity equals the saved one

#### Scenario: Refuse to overwrite another being
- **WHEN** an identity is saved to a path holding a different `entity_id`
- **THEN** saving raises an error and the file is unchanged

### Requirement: An identity is minted only at a fresh spawn
The cycle SHALL mint a new identity only when the state tree has no identity file and none of its own lived artifacts: the developmental stage file, the Phantasia world-model checkpoint, the Hypnos consolidation-divergence record and the perception desired-state. Fork snapshots and preservation bundles under the state tree SHALL NOT count as the tree's own lived artifacts. A state tree with own lived artifacts but no identity file SHALL receive a legacy identity derived deterministically from those artifacts, persisted at once. Revival, restart and merge SHALL NOT mint.

#### Scenario: Fresh spawn
- **WHEN** the cycle starts on a state tree with no identity file and no prior lived history
- **THEN** a minted identity with empty lineage is saved

#### Scenario: Lived tree without an identity
- **WHEN** the cycle starts on a state tree with a Phantasia checkpoint and no identity file
- **THEN** a legacy identity is saved, and starting again yields the same `entity_id`

#### Scenario: Fresh spawn beside other beings
- **WHEN** the cycle starts on a state tree with no identity file and none of its own lived artifacts, while `state/forks` and `state/preservation` hold other beings' snapshots and bundles
- **THEN** a minted identity is saved and the being resolves to gestation

### Requirement: Snapshots carry the identity and forks record lineage
Fork and preservation snapshots SHALL record the being's identity in their metadata. A fork SHALL receive a newly minted `entity_id` whose lineage is the parent's lineage followed by the parent's `entity_id`. A merge SHALL keep the target being's identity and record the merged-in being's `entity_id` as `merged_from_entity`.

#### Scenario: Fork lineage
- **WHEN** a being with lineage `[a]` and ID `b` is forked
- **THEN** the fork's identity has a new ID and lineage `[a, b]`

### Requirement: Revival restores identity and never mints
Revival SHALL restore the identity recorded in the bundle. A bundle without an identity SHALL revive with a legacy identity derived from its preservation ID, so that reviving the same bundle twice yields the same `entity_id`. Revival SHALL refuse when the target state tree already holds a different identity.

#### Scenario: Legacy bundle
- **WHEN** a bundle written before identities existed is revived twice into fresh trees
- **THEN** both revivals record the same legacy `entity_id`

#### Scenario: Conflict
- **WHEN** a bundle is revived into a tree whose identity file holds a different `entity_id`
- **THEN** revival raises an error and changes nothing

### Requirement: Prior history is scoped to the being's lineage
The lineage-scoped history query SHALL report prior lived history when any fork snapshot or preservation record carries the being's `entity_id` or an ID in its lineage, reading metadata and manifests only. Records belonging to other beings, and records without an identity, SHALL NOT count for a being with a known identity. A being whose identity cannot be determined SHALL count as having lived.

#### Scenario: Another being's bundle
- **WHEN** the state tree holds a preservation bundle of a different being and nothing of this being's lineage
- **THEN** the query reports no prior history

#### Scenario: Unknown identity
- **WHEN** the query is asked about a being with no determinable identity
- **THEN** it reports prior history

### Requirement: The identity is readable without decryption
Every encrypted container of a being's state SHALL have a plaintext identity record beside it holding the being's `entity_id` and `lineage`: a fork snapshot's `identity.json`, a preservation bundle's and a decommission backup's `manifest.json`, and a forked-being job's payload. Reading it SHALL NOT require decryption. When the container is opened, the in-container identity SHALL agree with the plaintext record, or loading SHALL fail.

#### Scenario: Sidecar without decryption
- **WHEN** a being's fork snapshot is saved with state encryption enabled
- **THEN** its directory holds a plaintext `identity.json` with the being's `entity_id` and `lineage`

#### Scenario: Disagreement fails
- **WHEN** a snapshot's plaintext identity record names a different `entity_id` from the identity inside the snapshot
- **THEN** loading raises an identity error

### Requirement: The identity format and legacy derivation are frozen
An `entity_id` SHALL be `ent-` or `legacy-` followed by 32 lowercase hexadecimal characters. A legacy ID SHALL be `legacy-` followed by the first 32 hexadecimal characters of the SHA-256 of its UTF-8 source string. The sources SHALL be `bundle:<preservation_id>`, and `tree:` followed by the SHA-256 hex of the newline-joined, sorted lines `<path relative to the state root>\0<SHA-256 hex of the file>` for each of the tree's own lived artifacts.

#### Scenario: Golden value
- **WHEN** the legacy identity of source `bundle:abc` is derived
- **THEN** its `entity_id` is `legacy-` followed by the first 32 hex characters of SHA-256 of `bundle:abc`
