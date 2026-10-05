# remote-bridge Specification

## Purpose
This capability adds an optional remote audio/video bridge that is disabled by default and injects remote operator senses into the perception modules while streaming generated speech and the conversation transcript back to clients. Remote senses follow the zero-persistence rule and respect the physical locus.

## Requirements

### Requirement: Remote A/V ingress/egress bridge, disabled by default
The cycle SHALL provide an optional WebSocket bridge
(`[remote_bridge]`, shipped `enabled = false`, default bind `127.0.0.1`) that
injects remote operator audio/video into the perception modules and streams
generated speech and the conversation transcript back to connected clients.
Remote video frames SHALL be decoded to in-memory images and passed to
`Topos.process_frame`; remote audio SHALL flow through the existing
`LiveMicrophone` VAD/utterance assembly via an injected network stream and
reach `Audition.process_audio` with `source_label = "remote"`; generated
speech SHALL be tapped from Vox via a composed `Player` without disabling
local playback; transcript events SHALL be forwarded from the
`lingua.external` and `audition.out` streams. When a shared-secret token is
configured, connections without it SHALL be rejected.

#### Scenario: Shipped config does not run the bridge
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[remote_bridge].enabled` is false and the cycle starts no bridge

#### Scenario: Remote frame reaches Topos
- **WHEN** a connected client sends a binary JPEG frame to `/ingest/video`
- **THEN** the bridge decodes it in memory and `Topos.process_frame` receives
  a PIL image

#### Scenario: Remote audio reaches Audition through the real VAD path
- **WHEN** a connected client streams int16 PCM containing an utterance to
  `/ingest/audio`
- **THEN** `Audition.process_audio` receives in-memory WAV bytes with
  `source_label = "remote"` after the existing utterance segmentation

#### Scenario: Generated speech streams to clients
- **WHEN** Vox plays a synthesized clip while a `/speech` client is connected
- **THEN** the client receives the WAV bytes and local playback still occurs

#### Scenario: Transcript forwarding
- **WHEN** an entity utterance lands on `lingua.external` or a transcription
  on `audition.out` while a `/transcript` client is connected
- **THEN** the client receives a JSON message carrying the role, text, and
  timestamp

#### Scenario: Token rejects unauthenticated clients
- **WHEN** `[remote_bridge].token` is non-empty and a client connects without
  presenting it
- **THEN** the connection is closed without processing any payload

### Requirement: Remote senses respect zero-persistence and the physical locus
The bridge SHALL NOT write remote frames, audio, or speech to disk — all
payloads live in memory only and are released after processing. While a
remote video or audio producer is connected (and `claim_senses` is true,
the default), the bridge SHALL mark the corresponding physical sense
not-desired via the `perception_state` API so physical and remote sensors do
not compete, and SHALL restore the prior desired state when the producer
disconnects. The bridge SHALL contain no process-termination or shell-exec
primitives.

#### Scenario: No disk artifacts from remote ingestion
- **WHEN** remote frames and audio are ingested and speech is streamed out
- **THEN** no new media/array files appear in `/tmp` or the project directory

#### Scenario: Physical camera yields to the remote camera
- **WHEN** a remote video producer connects with `claim_senses = true`
- **THEN** the desired physical-video state is set false, and is restored to
  its prior value on disconnect

#### Scenario: Source is attributed
- **WHEN** remote audio produces a transcription event
- **THEN** the event payload discloses the remote source label (never
  impersonating the physical microphone)

### Requirement: Non-loopback bridge binds require a token
The remote bridge SHALL refuse to bind to any address other than `127.0.0.1` unless a non-empty operator token is configured. The default bind SHALL remain loopback and the default token SHALL remain empty.

#### Scenario: Loopback bind starts without token
- **WHEN** the bridge is enabled with the default `host = "127.0.0.1"` and no token
- **THEN** it starts normally, relying on the tailnet ACL as the primary boundary

#### Scenario: Non-loopback bind without token fails closed
- **WHEN** the bridge is configured with `host = "0.0.0.0"` and an empty token
- **THEN** the bridge logs a clear error and refuses to start

### Requirement: Token is not transmitted in query string or subprotocol
The bridge SHALL accept the operator token via the `Authorization: Bearer <token>` header for non-browser clients. The token SHALL NOT be accepted in the WebSocket query string or as a `Sec-WebSocket-Protocol` subprotocol value, so it does not appear in URL history, referrers, or server logs.

#### Scenario: Browser client uses header-based authentication
- **WHEN** a browser client connects with the token in the query string
- **THEN** the server rejects the connection with HTTP 401

#### Scenario: Non-browser client uses Bearer header
- **WHEN** a client connects with `Authorization: Bearer <token>`
- **THEN** the server accepts the connection if the token is valid
