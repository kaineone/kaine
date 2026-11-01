## ADDED Requirements

### Requirement: The game stream is held until its conditions hold
A game-stream body or source SHALL be refused at boot until the game host is a tailnet peer, the direct-path, encryption and latency checks pass, and the client helper is installed. The refusal SHALL name the condition that failed.

#### Scenario: No host on the tailnet
- **WHEN** the configured game host is not a tailnet peer
- **THEN** boot refuses, naming the missing host

### Requirement: The Moonlight client runs as a separate program behind a minimal message set
The Moonlight-protocol client SHALL run as a separate helper process, never linked into the cycle, and SHALL exchange with the cycle over a socketpair only decoded video frames, PCM, gamepad state and a stop command. The helper SHALL write no frame or sample to disk and SHALL NOT use the library's recording callbacks.

#### Scenario: The cycle's dependencies
- **WHEN** the cycle's installed packages and imports are listed
- **THEN** no GPL-licensed streaming library is among them

### Requirement: Streams stay on a direct tailnet path, encrypted
Before each session the launcher SHALL refuse unless the host peer's path is direct, not relayed. The host SHALL be configured with mandatory stream encryption, and its ports SHALL be reachable only on the tailnet interface.

#### Scenario: A relayed path
- **WHEN** `tailscale status` shows the host peer as relayed
- **THEN** no session starts, and the reason says the path is relayed

### Requirement: Gamepad channels are learned, not mapped
A game-stream body SHALL declare the virtual gamepad's axes, triggers and buttons as channels. No code SHALL map a drive, goal or canonical channel to a gamepad control, and each title SHALL be its own body context.

#### Scenario: A new title
- **WHEN** the entity plays a title for the first time
- **THEN** its gamepad context starts untrained for that title, and earlier titles' contexts are unchanged

### Requirement: Only offline single-player titles from the operator's list
A session SHALL start only for a title on the operator's curated list, identified by its app id. The list SHALL admit only offline, single-player titles without kernel anti-cheat.

#### Scenario: A title not on the list
- **WHEN** a session is requested for an app id not on the list
- **THEN** no session starts

### Requirement: End-to-end latency is measured and bounded
The launcher SHALL measure the delay from a gamepad state change to a changed frame at session start, SHALL record it, and SHALL refuse or end the session above `max_latency_ms`.

#### Scenario: A slow stream
- **WHEN** the measured end-to-end latency exceeds the bound
- **THEN** the session ends with the measured value in the reason
