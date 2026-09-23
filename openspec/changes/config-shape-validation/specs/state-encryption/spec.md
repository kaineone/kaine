## ADDED Requirements

### Requirement: A configuration error never disables encryption
A component that reads `[security.state_encryption]` SHALL NOT treat a configuration that cannot be loaded or validated as a disabled or empty encryption section; it SHALL raise a configuration error. A process that performs cognitive-state file I/O SHALL NOT perform that I/O when its configured encryption posture could not be installed (for example the configuration failed to load or validate, or encryption is enabled and no key is available); it SHALL log an error naming the cause and leave those state operations unavailable instead of falling back to the disabled pass-through encryptor.

#### Scenario: Malformed configuration at Nexus startup
- **WHEN** Nexus reads the state-encryption section and the configuration fails to load or validate
- **THEN** Nexus logs an error naming the cause, does not construct its fork manager, and performs no fork or merge state I/O

#### Scenario: Encryption enabled without a key at Nexus startup
- **WHEN** `[security.state_encryption].enabled` is true and no key is available when Nexus starts
- **THEN** Nexus logs an error naming the missing key, does not construct its fork manager, and never writes a fork snapshot in plaintext

#### Scenario: Decommission cannot install the encryption posture
- **WHEN** `python -m kaine.lifecycle` (decommission) starts and the merged configuration cannot be loaded or validated, or the state-encryption posture cannot be installed
- **THEN** it reports a configuration error and exits before assessing divergence, capturing a backup or deleting anything, so it never judges or copies encrypted state through the pass-through encryptor

#### Scenario: Nexus reports disabled fork operations
- **WHEN** Nexus left its fork manager unconstructed because the encryption posture could not be installed
- **THEN** the fork listing reports that fork operations are unavailable, with the reason, instead of an empty list of forks

