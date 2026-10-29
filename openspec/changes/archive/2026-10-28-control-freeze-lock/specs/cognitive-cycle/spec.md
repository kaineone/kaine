## ADDED Requirements

### Requirement: Freeze-stack updates are serialized
Every update of the cycle-control file SHALL take an exclusive lock, read the current file, apply its change and write it back atomically through a unique temporary file, whichever process makes it. Concurrent updates SHALL NOT lose a freeze.

#### Scenario: Freeze-stack updates are serialized
- **WHEN** the cycle pushes a welfare freeze while the dashboard concurrently applies an operator resume of a different freeze
- **THEN** the welfare freeze is still in the stack
