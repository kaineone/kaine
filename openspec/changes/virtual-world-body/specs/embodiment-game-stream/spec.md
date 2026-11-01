## ADDED Requirements

### Requirement: The game stream is refused until its conditions hold
A game-stream body or source SHALL be refused at boot until the game host is a tailnet peer, Tailnet Lock is enabled with this node and the host signed, the host's stream ports answer, the encryption and latency checks pass, and the client helper is installed. The refusal SHALL name the condition that failed.

#### Scenario: No host on the tailnet
- **WHEN** the configured game host is not a tailnet peer
- **THEN** boot refuses, naming the missing host

### Requirement: The Moonlight client runs as a separate program behind a minimal message set
The Moonlight-protocol client SHALL be a separate helper program kept in its own repository, never linked into the cycle. It SHALL exchange with the cycle over a socketpair only decoded video frames, PCM, gamepad state and a stop command, SHALL send no keyboard, mouse or text event, SHALL write no frame or sample to disk, and SHALL NOT use the library's recording callbacks.

#### Scenario: The cycle's dependencies
- **WHEN** the cycle's installed packages and imports are listed
- **THEN** no GPL-licensed streaming library is among them

### Requirement: Streams run on a locked tailnet, encrypted
Before each session the launcher SHALL refuse unless `tailscale lock status` shows Tailnet Lock enabled and both this node and the host signed. The host SHALL be configured with mandatory stream encryption and its ports reachable only on the tailnet. The session record SHALL say whether the path was direct or relayed.

#### Scenario: Tailnet Lock off
- **WHEN** Tailnet Lock is not enabled on the tailnet
- **THEN** no session starts, and the reason names Tailnet Lock

### Requirement: KAINE's listeners are exposed only as declared
The boot preflight SHALL refuse when any KAINE listener binds to an address other than loopback, the container network, or the tailnet interface for a port the operator has listed. The docs SHALL give a tailnet ACL template that grants the KAINE node only the game host's stream ports.

#### Scenario: A dashboard on all interfaces
- **WHEN** the dashboard is configured to bind `0.0.0.0`
- **THEN** the preflight refuses, naming the listener

### Requirement: Gamepad channels are learned, not mapped
A game-stream body SHALL declare the virtual gamepad's sticks, triggers and face, shoulder and d-pad buttons as channels, and SHALL declare no Guide, home, Steam or share channel. No code SHALL map a drive, goal or canonical channel to a gamepad control, and each title SHALL be its own body context.

#### Scenario: A new title
- **WHEN** the entity plays a title for the first time
- **THEN** its gamepad context starts untrained for that title, and earlier titles' contexts are unchanged

### Requirement: Only offline single-player titles from the operator's list
A session SHALL start only for a title on the operator's curated list, identified by its app id. The list SHALL admit only offline, single-player titles without kernel anti-cheat.

#### Scenario: A title not on the list
- **WHEN** a session is requested for an app id not on the list
- **THEN** no session starts

### Requirement: End-to-end latency is measured before the entity perceives the stream
The launcher SHALL measure the delay from a gamepad state change to a changed frame before the stream is routed to the entity, using the probe input declared neutral for that title, SHALL record it, and SHALL refuse or end the session above `max_latency_ms`. A title without a declared neutral probe SHALL NOT be admitted.

#### Scenario: Session start
- **WHEN** a session starts
- **THEN** the probe runs before any frame or sound reaches the entity, and only the title's declared neutral input is sent

#### Scenario: A slow stream
- **WHEN** the measured end-to-end latency exceeds the bound
- **THEN** the session ends with the measured value in the reason

### Requirement: Same-host play yields the cards to the mind
On a host that also runs the entity, a session SHALL start only when the game card's free memory, read through NVML, covers the game's declared need plus the organ's measured awake peak plus a 1 GiB margin. It SHALL end with a named reason when either card's free memory falls below the margin, when the cycle latency or vision report rate leaves its band for 30 s, or when sleep begins.

#### Scenario: Sleep begins mid-session
- **WHEN** the entity falls asleep during a same-host session
- **THEN** the session ends before the sleep-time trainer touches the card

### Requirement: Same-host play runs on a separate display with a confined gamepad
On a host that also runs the entity, a game SHALL run on a display other than the operator's session, and its gamepad SHALL be visible only to the game's own container. Until a check proves both on the host, same-host sessions SHALL be refused.

#### Scenario: Before the spike
- **WHEN** a same-host session is requested and the display and confinement check has not passed
- **THEN** the session is refused, and the reason names the check

### Requirement: The game host is confined to the curated game, as reported by a host agent
A host check agent on the game host SHALL report, signed, over the tailnet: the application list holds only the curated titles; keyboard and mouse input are disabled; the game client is offline with notifications off; outbound internet is blocked except the tailnet, with a failing escape probe; and the session is confined. The launcher SHALL refuse a session when any check fails or the agent is absent.

#### Scenario: A desktop entry in the application list
- **WHEN** the agent reports a Desktop entry in the host's application list
- **THEN** no session starts, and the reason names the entry

#### Scenario: No agent
- **WHEN** the game host runs no check agent
- **THEN** no session starts, and the reason names the missing agent

### Requirement: Unobservable host facts are attestations, never verifications
A host fact that neither the agent nor the launcher can observe SHALL be recorded as a dated operator attestation, and SHALL NOT be reported as verified.

#### Scenario: A per-title setting stored elsewhere
- **WHEN** a title keeps an online setting the agent cannot read
- **THEN** the session record lists it as an operator attestation with its date

### Requirement: The path is monitored for the whole session
The launcher SHALL monitor the tailnet path throughout a session, SHALL record each change between direct and relayed, and SHALL end the session when the latency bound is exceeded.

#### Scenario: A fall back to a relay
- **WHEN** the path changes from direct to relayed mid-session
- **THEN** the change is recorded, and the session continues only while latency stays within the bound
