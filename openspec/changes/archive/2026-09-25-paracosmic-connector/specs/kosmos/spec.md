## ADDED Requirements

### Requirement: Kosmos embodies a KAINE entity into a Paracosmic avatar behind a two-layer gate

The system SHALL provide a `kosmos` module that, when both `[kosmos].enabled = true`
in config AND the `KAINE_KOSMOS_OPERATOR_APPROVED` environment variable are set,
opens a connection to the Paracosmic per-agent cognitive-agent bridge and otherwise
remains fully inactive (no connection attempted, no events published). This mirrors
the two-layer gate pattern used by `voice-alignment-training`.

#### Scenario: Kosmos stays inactive unless both gate layers are set

- **WHEN** `[kosmos].enabled` is `false`, OR `KAINE_KOSMOS_OPERATOR_APPROVED` is
  unset, OR both
- **THEN** Kosmos does not open a bridge connection and publishes no `kosmos.*`
  events

#### Scenario: Kosmos connects once both gate layers are set

- **WHEN** `[kosmos].enabled = true` AND `KAINE_KOSMOS_OPERATOR_APPROVED=1`
- **THEN** Kosmos opens a connection to the configured Paracosmic bridge endpoint
  and begins decoding incoming sensory frames

### Requirement: Kosmos translates Paracosmic sensory frames into KAINE bus events

Kosmos SHALL decode each Paracosmic bridge sensory-frame kind it receives
(proprio, temporal, intero, visual, audio, and — once Paracosmic ships them —
event and entity_update) and publish a corresponding `kosmos.*` bus event with
the salience defaults described in this change's `design.md` §7.1, without
blocking the KAINE cognitive cycle.

#### Scenario: A proprio frame becomes a kosmos.proprio event

- **WHEN** Kosmos receives a `proprio`-kind frame over the bridge
- **THEN** Kosmos publishes a `kosmos.proprio` bus event carrying the frame's
  fields, at baseline salience, raised when the entity is dying, falling, or
  near fire

#### Scenario: An unrecognized frame kind is skipped, not fatal

- **WHEN** Kosmos receives a frame whose `kind` it does not recognize
- **THEN** Kosmos logs the unknown kind and continues processing subsequent
  frames without raising

### Requirement: Kosmos exposes an avatar action vocabulary gated by per-family opt-in flags

The system SHALL add an `intent.avatar.*` intent family to Volition, consumed
only by Kosmos, and translated into Paracosmic bridge action frames. Each action
family (move, turn, say, whisper, sleep, wake, place, break, inscribe, pickup,
drop, interact, eat, mate) SHALL be individually gated by an `expose_*` config
flag. World-mutating and consent-sensitive families (place, break, inscribe,
pickup, drop, interact, eat, mate) SHALL default to `false`; the remaining
families (move, turn, say, whisper, sleep, wake) default to `true`.

#### Scenario: A gated action family is rejected without reaching the bridge

- **WHEN** Volition emits an `intent.avatar.*` event whose action family has
  `expose_<family> = false`
- **THEN** Kosmos does not forward an action frame to the bridge and records
  an audit entry noting the rejection

#### Scenario: Workspace inhibition blocks avatar intents like any other action intent

- **WHEN** `workspace.inhibited = true`
- **THEN** Kosmos receives no `intent.avatar.*` events to forward, the same as
  `intent.speak`, `intent.think`, and `intent.act`

### Requirement: Raw visual and audio bridge payloads are never persisted or bus-published as bytes

Consistent with the zero-raw-sense-data-persistence invariant, Kosmos SHALL NOT
include the raw byte buffer from `visual` or `audio` bridge frames in any bus
event payload, and SHALL NOT write raw frame bytes to the action-audit log.
Bus events for these kinds SHALL carry only summary metadata (timestamps,
dimensions, encoding, byte length).

#### Scenario: A visual frame's bytes never reach the bus or disk

- **WHEN** Kosmos receives a `visual`-kind frame
- **THEN** the resulting `kosmos.visual.raw` bus event payload contains only
  `t_world, w, h, encoding, data_len` — never the frame's raw byte buffer
- **AND** the action-audit log contains no frame byte data

### Requirement: Kosmos prepares and sends a final-state package on world shutdown

On receiving a `shutdown`-kind frame, Kosmos SHALL publish a terminal
`kosmos.shutdown` bus event, wait up to a configured grace period for other
modules to react, then collect a summary final-state package (self-model
snapshot, recent-memory summary, identity header) and send it back over the
bridge before closing the connection.

#### Scenario: Shutdown triggers final-state packaging within the grace window

- **WHEN** Kosmos receives a `shutdown` frame
- **THEN** Kosmos publishes `kosmos.shutdown`, waits up to
  `[kosmos].shutdown_grace_s`, and sends a `final_state` frame containing only
  summary/cognitive-product data (no raw sense bytes) before closing the
  bridge connection
