## ADDED Requirements

### Requirement: The wizard offers module presets with a hardware-aware recommendation
The wizard's module step SHALL offer three choices: the base thesis (exactly the `[modules]` table of `config/profiles/thesis_test.toml`), the full entity (every cognitive module on, the embodiment modules and Echo off), and a custom per-module selection that starts from the recommended preset. It SHALL recommend the full entity when the host's tier recommendation is tier 2 or 3 without required module residency, and the base thesis otherwise or when no recommendation is available, and SHALL state the reason. The non-interactive mode SHALL apply the recommendation.

#### Scenario: A capable host is recommended the full entity
- **WHEN** the tier probe recommends tier 3
- **THEN** the wizard recommends the full entity and, if the operator accepts, writes every cognitive module on

#### Scenario: A constrained host is recommended the base thesis
- **WHEN** the tier probe recommends tier 1, or tier 2 with residency required, or no recommendation is available
- **THEN** the wizard recommends the base thesis and, if accepted, writes the profile's module set
