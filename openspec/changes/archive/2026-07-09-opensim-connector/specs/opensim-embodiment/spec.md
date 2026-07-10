## ADDED Requirements

### Requirement: A Mundus module embodies the entity in an OpenSim grid behind a two-layer gate

The system SHALL provide a `mundus` module that connects a KAINE entity to an
OpenSimulator avatar through a forked Second Life viewer driven over LEAP, and it
SHALL initialize only when both the config flag `[mundus].enabled = true` and the
environment variable `KAINE_MUNDUS_OPERATOR_APPROVED=1` are set. The shipped
configuration SHALL have the module off.

Mundus owns a local bridge socket to a LEAP shim that runs inside the viewer; the
shim translates between the viewer's LEAP LLSD protocol and the length-prefixed
MessagePack bridge contract Mundus consumes (the same transport the Kosmos module
uses). The viewer↔OpenSim link MAY cross the operator's Tailscale network, but the
LEAP bridge and any frame side-channel SHALL be loopback-local to the KAINE host.

#### Scenario: Gate closed means no connection

- **WHEN** the system boots with `[mundus].enabled = false` or
  `KAINE_MUNDUS_OPERATOR_APPROVED` unset
- **THEN** the module's `initialize()` is a no-op and no bridge connection is opened

#### Scenario: Gate open binds the avatar

- **WHEN** both the config flag and the environment approval are set and the LEAP
  shim is reachable
- **THEN** Mundus connects, emits a first `mundus.proprio` event, and the cognitive
  cycle continues to run without being blocked by bridge I/O

### Requirement: The embodiment viewer perceives as the avatar, first-person

The connector SHALL configure the embodiment viewer so the entity perceives from its
avatar rather than a free camera: the spatial-audio listener MUST be set to the
**avatar position** (not the default camera position), and the camera MUST be locked
to **mouselook** (first-person POV) so any captured visual frame is the avatar's own
view. These settings SHALL be applied at bind and re-asserted if an in-world action
drops them.

#### Scenario: Sound is heard from the avatar's position

- **WHEN** the embodiment viewer binds to the bot avatar
- **THEN** the listener/ear location is set to the avatar position via the viewer's
  control API
- **AND** it is not left at the default camera position

#### Scenario: The view stays first-person

- **WHEN** an in-world action (e.g. sit) would drop the camera out of mouselook
- **THEN** the connector re-asserts mouselook
- **AND** a captured visual frame reflects the avatar's first-person POV

### Requirement: World state is published as bus events without persisting raw frames

The system SHALL translate world state from the bridge into `mundus.*` bus events
(`mundus.proprio`, `mundus.scene`, `mundus.entity`, `mundus.chat`, `mundus.notice`,
`mundus.action.result`, and optionally `mundus.visual.raw`), and any rendered-frame
bytes MUST NOT appear in a bus event payload — frames flow off a side channel to a
real-time consumer and are discarded, with the event carrying only `w, h, encoding,
data_len`.

Symbolic perception (`mundus.scene` from nearby objects, `mundus.entity` from
nearby avatars, `mundus.proprio` from agent position) SHALL be available without any
viewer patch, so the connector is useful before in-world vision is built. In-world
text chat received as `mundus.chat` SHALL also be synthesized into an
`audio.in.transcription` event tagged `source_label="opensim:<name>"` so existing
Audio_In consumers see it through their normal path, and it SHALL NOT be routed
through speech-to-text.

#### Scenario: A rendered frame never lands in a bus payload

- **WHEN** the viewer's frame-capture op delivers RGB bytes for vision
- **THEN** the bytes reach the visual consumer over the side channel
- **AND** the `mundus.visual.raw` event payload contains only metadata
  (`w, h, encoding, data_len`), never the buffer

#### Scenario: In-world speech reaches cognition without STT

- **WHEN** another avatar speaks in local chat and the viewer surfaces the text
- **THEN** Mundus publishes `mundus.chat` and synthesizes an
  `audio.in.transcription` event so Mnemos and Eidolon consume it normally
- **AND** no audio is sent to the speech-to-text pipeline
