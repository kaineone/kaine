## ADDED Requirements

### Requirement: Tier recommendation accounts for memory and keeps the GPU
The tier recommender SHALL compute a memory budget as system RAM on unified-memory hosts and the smaller of system RAM and accelerator memory on discrete hosts, and SHALL recommend: Tier 3 for two or more accelerators with a budget of at least 16 GB; Tier 2 for one accelerator with a budget of at least 16 GB; Tier 2 with module residency required for an accelerator host with a budget from 6 GB up to 16 GB; Tier 1 below 6 GB or without an accelerator. The first-run wizard SHALL show the recommendation with its reason and SHALL apply the matching profile only when the operator confirms.

#### Scenario: 8 GB unified Jetson
- **WHEN** the host has one unified-memory accelerator and 8 GB of RAM
- **THEN** the recommender proposes Tier 2 with module residency required and does not recommend the CPU-only Tier 1

#### Scenario: Operator declines the recommendation
- **WHEN** the wizard proposes a profile and the operator declines
- **THEN** no profile is written and the existing configuration is unchanged
