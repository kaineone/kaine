## ADDED Requirements

### Requirement: Nexus reports incomplete setup without a traceback
When the event bus cannot be configured, for example because no Redis password
exists yet, `python -m kaine.nexus` SHALL exit with status 1. It SHALL log a
single message that names the setup step that fixes the problem, and SHALL NOT
print a traceback.

#### Scenario: Fresh clone before Redis setup
- **WHEN** Nexus is started before `scripts/redis-bootstrap.sh` has run
- **THEN** it exits 1
- **AND** it logs a message naming `bash scripts/redis-bootstrap.sh`
- **AND** no traceback is printed

### Requirement: Login lands on a mounted console
After a successful sign-in, Nexus SHALL redirect the operator to a console
that is mounted:

- `/` when the conversation console is enabled;
- otherwise `/diagnostics/`.

Nexus SHALL refuse to start when neither console is enabled, since sign-in
would lead nowhere.

#### Scenario: Default configuration
- **WHEN** conversation is disabled and diagnostics is enabled
- **AND** the operator signs in
- **THEN** the login response redirects to `/diagnostics/`

#### Scenario: Conversation enabled
- **WHEN** conversation is enabled
- **AND** the operator signs in
- **THEN** the login response redirects to `/`

#### Scenario: Nothing to serve
- **WHEN** both the conversation console and diagnostics are disabled
- **THEN** Nexus exits 1 with a message saying that no console is enabled
