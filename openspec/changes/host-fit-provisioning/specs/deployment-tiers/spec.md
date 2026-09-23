## ADDED Requirements

### Requirement: Tier recommendation accounts for memory and keeps the GPU
The tier recommender SHALL compute a memory budget as system RAM on unified-memory hosts and the smaller of system RAM and accelerator memory on discrete hosts, and SHALL recommend: Tier 3 for two or more accelerators with a budget of at least 16 GB; Tier 2 for one accelerator with a budget of at least 16 GB; Tier 2 with module residency required for an accelerator host with a budget from 6 GB up to 16 GB; Tier 1 below 6 GB or without an accelerator. The first-run wizard SHALL show the recommendation with its reason and SHALL record the matching tier as `[deployment].tier` in the operator's local configuration only when the operator confirms. The tier SHALL be applied as its own configuration layer between the module-selection profile (the base-thesis `thesis_test` profile by default, or `--profile` / `KAINE_PROFILE`) and the operator's configuration, so recording a tier never replaces the selected module set; the cycle and the pre-boot check SHALL load configuration through the same layering.

#### Scenario: 8 GB unified Jetson
- **WHEN** the host has one unified-memory accelerator and 8 GB of RAM
- **THEN** the recommender proposes Tier 2 with module residency required and does not recommend the CPU-only Tier 1

#### Scenario: Operator declines the recommendation
- **WHEN** the wizard proposes a profile and the operator declines
- **THEN** no tier is written and the existing configuration is unchanged

#### Scenario: Recorded tier keeps the base-thesis modules
- **WHEN** the operator accepts a Tier 2 recommendation and later boots without `--profile` or `KAINE_PROFILE`
- **THEN** the cycle loads the base-thesis module set with the Tier 2 backend settings layered on top, and the pre-boot check validates the same merged configuration
