## ADDED Requirements

### Requirement: The runner surfaces a welfare freeze and never lifts it
The study runner SHALL read each running child's freeze stack, SHALL surface a `welfare` entry in the step's status and log, and SHALL NOT lift it. A step that ends while a welfare freeze noticed on the running child is still held SHALL be recorded with the outcome `failed:welfare` and the freeze's start and reason.

#### Scenario: The child is frozen by the welfare safety net
- **WHEN** a running child's freeze stack holds a `welfare` entry and the step then ends
- **THEN** the step is recorded `failed:welfare`, `status` shows the freeze, and the freeze is still in the child's control file

#### Scenario: An earlier child's control file
- **WHEN** a child exits at boot and the step directory holds a welfare entry from an earlier child
- **THEN** the step keeps its own failure outcome
