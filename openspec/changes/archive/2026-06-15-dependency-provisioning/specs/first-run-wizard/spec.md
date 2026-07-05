## ADDED Requirements

### Requirement: Wizard detects and helps provision external dependencies

The first-run wizard SHALL detect the external service dependencies required by
the enabled modules and report, for each, whether it is already running. For
dependencies provisionable by a single in-repo script or installer command, the
wizard SHALL show the exact command and run it ONLY on explicit operator consent.
For heavy GPU services that cannot be honestly installed in one step, the wizard
SHALL print real setup guidance and a docs link and run nothing. The wizard SHALL
NOT install anything without consent and SHALL NOT crash on a provisioning
failure.

#### Scenario: A running dependency is not offered

- **WHEN** a required service is already listening on its port
- **THEN** the wizard reports it as running and offers no install

#### Scenario: A command-provisionable dependency runs only on consent

- **WHEN** a required command-provisionable service (e.g. Redis, Ollama) is not
  running
- **THEN** the wizard prints the exact command
- **AND** runs it only if the operator consents, otherwise prints how to run it later

#### Scenario: A heavy GPU service is guided, never auto-installed

- **WHEN** a required guide-only service (e.g. Speaches, Chatterbox) is not running
- **THEN** the wizard prints its setup steps and docs link
- **AND** never runs an install command for it

#### Scenario: A provisioning failure does not crash the wizard

- **WHEN** a consented provisioning command fails
- **THEN** the wizard reports the failure and the manual command
- **AND** continues to the next step without raising
