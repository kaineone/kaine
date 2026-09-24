## ADDED Requirements

### Requirement: Browser setup is private to the local machine
`python -m kaine.setup --web` SHALL serve the setup interface only on
127.0.0.1. It SHALL require a one-time launch token, carried in the URL it
opens, which is exchanged for a session cookie and then invalidated. It SHALL
reject any state-changing request whose session, Host header or Origin header
does not match. It SHALL shut down when setup finishes or after 30 minutes
without activity.

#### Scenario: Request without the session
- **WHEN** a request to change a setting arrives without a valid setup session
- **THEN** it is rejected
- **AND** nothing is written

#### Scenario: Launch token is single-use
- **WHEN** the launch URL is opened a second time after the session was established
- **THEN** the token is refused

### Requirement: One step model drives both setup front ends
The terminal wizard and the browser setup SHALL be generated from the same
declarative step definitions. Identical answers SHALL produce identical
configuration from either front end.

#### Scenario: Parity
- **WHEN** the same answers are given through the terminal wizard and through the browser setup
- **THEN** the resulting operator configuration is identical

### Requirement: Setup writes only the keys it owns
Setup SHALL write only configuration keys on its owned-key allowlist, and
SHALL merge them into an existing operator override rather than replacing
the file. The allowlist SHALL exclude `[research]`, every operator-presence
gate and `[nexus].non_loopback_allowed`.

#### Scenario: Hand edits survive a re-run
- **WHEN** the operator override contains a key that setup does not own
- **AND** setup is run again and saved
- **THEN** that key and its value are unchanged

#### Scenario: Research mode cannot be enabled from setup
- **WHEN** any combination of setup answers is saved
- **THEN** the operator override contains no `[research]` table written by setup

### Requirement: Long setup tasks run only on explicit consent, with progress
Downloads, installs, service bootstraps and starting Nexus SHALL each start
only on an explicit operator action for that task. Each SHALL show live
progress and a plain-language result. A failed task SHALL report what
happened and what to do next without ending the setup session.

#### Scenario: No silent install
- **WHEN** a setup page that offers a download is displayed
- **THEN** nothing is downloaded until the operator starts that task

#### Scenario: A failed task does not end setup
- **WHEN** a bootstrap task fails
- **THEN** the page reports the failure and the remedy
- **AND** the operator can continue to the other steps

### Requirement: Setup never starts the entity
The setup interface SHALL NOT start or spawn the entity, and SHALL expose no
action that runs `kaine.cycle`. Starting Nexus is permitted.

#### Scenario: No entity-start route
- **WHEN** the setup server's routes are enumerated
- **THEN** none of them starts `kaine.cycle`
