## ADDED Requirements

### Requirement: Tier recommendation accounts for memory on accelerator hosts
The tier recommender SHALL budget by system RAM on unified-memory hosts and by the smaller of system RAM and accelerator memory on discrete hosts, and the first-run wizard SHALL show the recommendation and apply the matching profile only when the operator confirms.

#### Scenario: 8 GB unified Jetson
- **WHEN** the host has one unified-memory accelerator and 8 GB of RAM
- **THEN** the recommender proposes Tier 1, not Tier 2

#### Scenario: Operator declines the recommendation
- **WHEN** the wizard proposes a profile and the operator declines
- **THEN** no profile is written and the existing configuration is unchanged
