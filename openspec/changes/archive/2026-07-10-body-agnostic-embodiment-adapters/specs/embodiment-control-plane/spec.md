# embodiment-control-plane (spec delta — DESIGN ONLY)

## ADDED Requirements

### Requirement: Mundus is a body-agnostic control plane driven by pluggable adapters
The `mundus` module SHALL be a body-agnostic control surface that routes the entity's
perception and action to and from a body through a pluggable `EmbodimentAdapter`,
rather than binding to any one platform. The module core SHALL contain no wire
protocol, transport, or platform-specific vocabulary; each body (a virtual world, a VR
runtime, a robot, or another effector platform) SHALL be a separate adapter the core
drives through one narrow interface. This supersedes the reference-body-bound Mundus of
`reference-connector`, whose viewer/wire-shim binding becomes one adapter behind this seam.

#### Scenario: The core is platform-independent
- **WHEN** a new body is added
- **THEN** it is implemented as an `EmbodimentAdapter` and selected in config, and the
  Mundus core is not modified to support it

#### Scenario: Only the selected body is active
- **WHEN** the module initializes with a chosen adapter
- **THEN** it constructs and drives only that adapter, and perceives/acts through it
  rather than through a script

### Requirement: An adapter declares a capability descriptor the core reads
Each adapter SHALL declare a capability descriptor — its feed-kind→(bus event, baseline
salience) map, its symbolic action families with default exposure, its continuous
channels (if any), and the payload keys carrying raw sense buffers — and the core SHALL
read behavior from that descriptor instead of from any hardcoded platform table. The
adapter SHALL NOT publish to the bus itself; it SHALL only produce feed frames and
accept actions, so salience policy and persistence stripping stay in the core.

#### Scenario: Feed mapping comes from the descriptor
- **WHEN** an adapter yields a feed frame of a given `kind`
- **THEN** the core maps it to the bus event and baseline salience named in the
  descriptor, and drops any declared raw-buffer key before publishing

#### Scenario: Action vocabulary comes from the descriptor
- **WHEN** the core evaluates whether an `intent.avatar.<family>` may act
- **THEN** the family must appear in the descriptor and be exposed, and a family absent
  from the descriptor is rejected and logged, never sent to the body

### Requirement: The core gates enablement, locus, and exposure platform-independently
The core SHALL enforce, independent of adapter, the two-layer enable gate
(`[mundus].enabled = true` AND `KAINE_MUNDUS_OPERATOR_APPROVED=1`), the
`locus == "virtual"` action gate via `perception_state`, and per-family exposure gating,
before any action reaches the adapter. The shipped configuration SHALL keep the module
off. World-mutating or consent-sensitive families (relocate-in-one-step, direct object
manipulation) SHALL default unexposed.

#### Scenario: Gate closed means no body I/O
- **WHEN** the config flag is false or the environment approval is unset
- **THEN** `initialize()` is a no-op, no adapter is opened, and no perception or action
  crosses the seam

#### Scenario: Action is refused when the locus is not virtual
- **WHEN** the entity's perceptual locus is not `virtual`
- **THEN** the core drops the action without calling the adapter, regardless of exposure

### Requirement: Raw sense data never persists, enforced by the core via the descriptor
The core SHALL strip every raw sense buffer named by the adapter's descriptor before an
event is published, so a rendered frame buffer or equivalent raw payload never reaches
the bus or disk. This zero-raw-persistence invariant SHALL hold for every adapter and
SHALL be verified by test.

#### Scenario: A visual frame publishes metadata only
- **WHEN** an adapter yields a frame carrying a rendered buffer under a declared
  raw-buffer key
- **THEN** the core publishes the frame metadata with the buffer removed, and the buffer
  is never written anywhere

### Requirement: The descriptor carries continuous channels for future graded control
The capability descriptor SHALL be able to express clamped continuous setpoint channels
(for VR-style or robotic graded control) alongside symbolic families, and the core SHALL
route continuous setpoints to the adapter's continuous sink, clamped to each channel's
declared range and gated per channel (default unexposed) and by locus. The canonical
continuous channel vocabulary SHALL be `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch`,
and `interact` (the `intuitive-embodiment-control-surface` set), so every graded-control
adapter and that change share one vocabulary. An adapter that
declares no continuous channels SHALL reject setpoints as unsupported rather than
silently dropping them. This change provides the shape only; wiring a continuous motor
producer is out of scope (it is `intuitive-embodiment-control-surface`).

#### Scenario: Continuous setpoints are clamped and gated
- **WHEN** a continuous setpoint arrives for a declared channel while the locus is
  virtual and the channel is exposed
- **THEN** the core clamps it to the channel's range and forwards it to the adapter's
  continuous sink

#### Scenario: A symbolic-only body rejects setpoints
- **WHEN** a setpoint is routed to an adapter whose descriptor declares no continuous
  channels
- **THEN** the adapter reports the channel unsupported and the core logs it, taking no
  body action

### Requirement: The reference adapter preserves the prior behavior and is marked transitional
The reference adapter SHALL reproduce the pre-refactor Mundus behavior bit-for-bit — the
same loopback bridge listener, the same length-prefixed-MessagePack frames and `reqid`
generation, the same single-connection semantics, the same feed→event map, the same
default exposures, and the same speech-mirror shape — and it SHALL declare itself
transitional in its descriptor so its later removal is an expected, bounded operation. A
test SHALL assert the adapter's descriptor equals the prior module constants so any
behavior drift fails continuous integration.

#### Scenario: The reference-body path is unchanged after the refactor
- **WHEN** the reference adapter is selected and the wire shim connects
- **THEN** perception events, action frames, and the speech mirror are indistinguishable
  from the pre-refactor module, and the existing Mundus tests pass

### Requirement: Configuration selects exactly one adapter and fails closed on an unknown name
The system SHALL select the active body through `[mundus].adapter`, construct only that
adapter from its nested `[mundus.<adapter>]` settings, and fail closed at boot on an
unknown adapter name rather than binding nothing silently. Adapter-specific settings
SHALL live under the adapter's own table, not flat in `[mundus]`.

#### Scenario: Unknown adapter halts boot
- **WHEN** `[mundus].adapter` names an adapter that does not exist
- **THEN** boot fails with a clear error and no partial/blind embodiment is constructed

#### Scenario: Adapter-scoped settings
- **WHEN** `[mundus].adapter = "reference"`
- **THEN** the core reads bridge host/port and exposure flags from `[mundus.reference]`,
  and settings for other adapters are ignored
