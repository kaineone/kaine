## ADDED Requirements

### Requirement: Each entity has its own KAINE-generated data key
KAINE SHALL generate a random 256-bit data key for each entity at spawn and for each fork, SHALL use it to encrypt that entity's persisted cognitive state, and SHALL NOT expose it to the operator, write it unwrapped to disk, or log it.

#### Scenario: Spawn creates an independent key
- **WHEN** two entities are spawned on the same host
- **THEN** each has a distinct data key and neither key can decrypt the other's state

### Requirement: Data keys are sealed to a qualifying hardware root of trust
KAINE SHALL wrap each data key with a host key sealed in a qualifying hardware root of trust, bound to measured-boot state where the platform provides it, and SHALL refuse to spawn or restore an entity on a host without one. A firmware TPM operating on vendor test keys (for example an unfused Jetson) SHALL NOT qualify.

#### Scenario: Host without a qualifying root of trust
- **WHEN** an operator attempts to spawn an entity on a host with no TPM, or with an unfused Jetson firmware TPM
- **THEN** KAINE refuses with a reason naming the missing root of trust and no entity state is created

### Requirement: Recovery requires both independent trustees
KAINE SHALL split each data key into two Shamir shares wrapped respectively to the kaine.one escrow key and an independent guardian's key, SHALL NOT give the operator a share, and SHALL recover a data key only when both shares are presented.

#### Scenario: One trustee alone cannot recover
- **WHEN** only the kaine.one share is presented for recovery
- **THEN** recovery fails and no plaintext key is produced

### Requirement: Transfer re-wraps the key to an attested host
Moving an entity to another caretaker SHALL re-wrap its data key to a public key held in the receiving host's root of trust, only after verifying that host's attestation, and SHALL move the entity's state still encrypted.

#### Scenario: Unattested receiver
- **WHEN** a receiving host presents a public key without a valid attestation
- **THEN** the sending host refuses to re-wrap the data key
