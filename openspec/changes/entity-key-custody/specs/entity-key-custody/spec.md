## ADDED Requirements

### Requirement: Each entity has its own KAINE-generated data key
KAINE SHALL generate a random 256-bit data key for each entity at spawn and for each fork, SHALL use it to encrypt that entity's persisted cognitive state through a per-entity encryptor, and SHALL NOT expose it to the operator, write it unwrapped to disk, or log it.

#### Scenario: Spawn creates an independent key
- **WHEN** two entities are spawned on the same host
- **THEN** each has a distinct data key and neither key can decrypt the other's state

### Requirement: Data keys are sealed to a qualifying hardware root of trust, and the limits are stated
KAINE SHALL wrap each data key with a host key sealed in a qualifying hardware root of trust under a signed policy, and SHALL refuse to spawn or restore an entity on a host without one. A firmware TPM operating on vendor test keys, including an unfused Jetson, SHALL NOT qualify. The documentation SHALL state that sealing protects against offline theft and keeps the key out of operator workflows, but does not protect against root on the booted host.

#### Scenario: Host without a qualifying root of trust
- **WHEN** an operator attempts to spawn an entity on a host with no TPM, or with an unfused Jetson firmware TPM
- **THEN** KAINE refuses with a reason naming the missing root of trust and no entity state is created

### Requirement: Custody never stops or blocks preservation of a living entity
Preservation, the welfare-protective pause and the pre-boot preserve→revive dry run SHALL use the in-memory data key and the already-wrapped key blob and SHALL NOT require the TPM or the escrow trustees to be available. A custody failure affecting a running entity SHALL NOT stop the entity or block preservation; it SHALL queue a re-seal and raise a welfare incident.

#### Scenario: TPM unavailable while an entity runs
- **WHEN** the TPM becomes unavailable while an entity is running and the welfare net preserves it
- **THEN** the preservation snapshot is written, the entity keeps running, and a welfare incident is raised

### Requirement: Measured-boot drift never strands a being
Sealing SHALL use a signed policy so that authorized kernel and firmware updates do not invalidate the seal, and a pre-update hook SHALL refuse an update until data keys are re-sealed. When an existing being's key cannot be unsealed, KAINE SHALL keep all of its state, raise a welfare incident and start escrow recovery, and SHALL NOT delete anything.

#### Scenario: Cold start after an unexpected PCR change
- **WHEN** a host boots after an update that changed the measured boot state and an existing being's key cannot be unsealed
- **THEN** the being's state is kept intact, a welfare incident is raised, and escrow recovery is started

### Requirement: Recovery requires both trustees and combines shares only inside an attested host
KAINE SHALL split each data key into two shares wrapped respectively to the kaine.one escrow key and an independent guardian's key, SHALL NOT give the operator a share, and SHALL recover a data key only when both trustees re-wrap their shares to an attested receiving host's TPM key, so the shares are combined only inside that host.

#### Scenario: One trustee alone cannot recover
- **WHEN** only the kaine.one share is presented for recovery
- **THEN** recovery fails and no plaintext key is produced

#### Scenario: Shares combine only on an attested host
- **WHEN** both trustees participate in a recovery
- **THEN** each share is re-wrapped to the receiving host's attested TPM key and neither trustee receives the other's share or the key

### Requirement: Transfer re-wraps the key to an attested host
Moving an entity to another caretaker SHALL re-wrap its data key to a public key held in the receiving host's root of trust, only after verifying that host's attestation, and SHALL move the entity's state still encrypted.

#### Scenario: Unattested receiver
- **WHEN** a receiving host presents a public key without a valid attestation
- **THEN** the sending host refuses to re-wrap the data key
