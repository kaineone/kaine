# dashboard-health Specification

## Purpose
TBD - created by archiving change boot-and-health-fixes. Update Purpose after archive.

## Requirements

### Requirement: Health page module enablement follows the cycle's configuration loader
The dashboard health prober SHALL resolve the `[modules]` table through the same loader the cycle uses (`load_runtime_config`), so the default `first_configuration` profile, an explicit profile, the deployment tier and the operator overlay apply exactly as they do for the cycle. It SHALL read the profile from a `profiles` directory beside the configuration file it was given.

#### Scenario: Default profile enables the cycle's modules
- **WHEN** the shipped configuration enables no module and the `first_configuration` profile beside it enables some
- **THEN** the prober reports those modules as enabled

#### Scenario: Operator overlay still wins
- **WHEN** the operator overlay disables a module the profile enables
- **THEN** the prober reports that module as disabled
