## ADDED Requirements

### Requirement: Browser setup is private to the local machine
`python -m kaine.setup --web` SHALL serve the setup interface only on
127.0.0.1. It SHALL require a one-time launch token, carried in the URL it
opens, which is exchanged for a session cookie and then invalidated, and
which expires two minutes after launch if unused. Every request other than the
token exchange SHALL require the session. State-changing requests SHALL also
be rejected unless the Host and Origin headers match. Responses carrying a
secret SHALL NOT be cacheable. The server SHALL shut down when setup finishes,
or after 30 minutes without activity, where a running job counts as activity.

#### Scenario: Request without the session
- **WHEN** a request to change a setting arrives without a valid setup session
- **THEN** it is rejected
- **AND** nothing is written

#### Scenario: Reads need the session too
- **WHEN** a progress stream or the sign-in token reveal is requested without a valid setup session
- **THEN** it is rejected

#### Scenario: Unused launch token expires
- **WHEN** the launch URL is first opened more than two minutes after launch
- **THEN** the token is refused

#### Scenario: Idle shutdown waits for running jobs
- **WHEN** a download is still running after 30 minutes without page activity
- **THEN** the server stays up until the job ends

#### Scenario: Launch token is single-use
- **WHEN** the launch URL is opened a second time after the session was established
- **THEN** the token is refused

### Requirement: Browser setup shares the Nexus brand and styling
The browser setup SHALL use the same brand guidelines and styling as Nexus:
- it serves Nexus's stylesheet and fonts from the Nexus static assets rather than from copies;
- it uses the same layout and wordmark;
- it styles any setup-specific component only with Nexus's design tokens, introducing no new colours or font families.

#### Scenario: Same stylesheet as Nexus
- **WHEN** a setup page is loaded
- **THEN** the stylesheet it links is byte-identical to the one Nexus serves

#### Scenario: No off-brand styling
- **WHEN** the setup-specific stylesheet is inspected
- **THEN** it contains no literal colour values and no font families that Nexus does not use

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
the file. The allowlist SHALL exclude `[research]`, which the research
harness owns, every operator-presence gate, and
`[nexus].non_loopback_allowed`.

#### Scenario: Hand edits survive a re-run
- **WHEN** the operator override contains a key that setup does not own
- **AND** setup is run again and saved
- **THEN** that key and its value are unchanged

#### Scenario: Research configuration is not a setup choice
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

### Requirement: Spawning is a deliberate, gated action
The setup interface SHALL start the entity only through a single spawn action
on the finish page. That action SHALL require a welfare acknowledgement given
on that page, a passing end-to-end pre-boot check, and a separate
confirmation, and SHALL start the cycle through the supervised start path. No
other setup step, job or route SHALL start `kaine.cycle`. The pre-boot check
SHALL be the same shared preflight the terminal path uses. Spawn SHALL refuse
while a cycle is already running, and setup SHALL refuse to save configuration
while one is running. The cycle and Nexus SHALL run detached from the setup
server, so that setup's exit never ends them. The welfare acknowledgement SHALL
be appended to a local record with its time and text version.

#### Scenario: Pre-boot check failing
- **WHEN** the operator requests spawn while any pre-boot check fails
- **THEN** the entity is not started
- **AND** the page names the failing check and its remedy

#### Scenario: Acknowledgement missing
- **WHEN** spawn is requested without the welfare acknowledgement on that page
- **THEN** the entity is not started

#### Scenario: Only one entity-start route
- **WHEN** the setup server's routes are enumerated
- **THEN** exactly one of them can start `kaine.cycle`, and it is the gated spawn action

#### Scenario: Other steps never spawn
- **WHEN** any other setup step or job completes
- **THEN** no cycle process has been started

#### Scenario: One entity at a time
- **WHEN** spawn is requested while a cycle is already running
- **THEN** no second cycle is started
- **AND** the page says an entity is already running

#### Scenario: No config rewrite under a running entity
- **WHEN** setup tries to save configuration while a cycle is running
- **THEN** nothing is written
- **AND** the page explains why

#### Scenario: Setup exit leaves the entity running
- **WHEN** the setup server exits or times out after a successful spawn
- **THEN** the cycle and Nexus processes keep running

#### Scenario: Terminal and browser agree on readiness
- **WHEN** the pre-boot check runs from the browser and from the terminal on the same machine
- **THEN** both run the same checks and reach the same result
