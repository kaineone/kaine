# perception-locus Specification

## Purpose

Defines the perception-locus contract shipped by the live `kaine/modules/perception/`
module: the single authority that binds the entity's perceptual organs to exactly one
world at a time (physical XOR virtual), the operator's live control and lock over it
from Nexus, and the gated policy under which the entity may switch its own locus. This
contract is body-agnostic — it holds regardless of which embodiment adapter provides the
virtual world.

## Requirements

### Requirement: Perception binds to one world at a time (physical XOR virtual)

The system SHALL maintain a single `perception_locus` (`physical`, `virtual`, or
`off`) as the sole authority for which world the entity's perceptual organs bind to,
and it MUST enforce mutual exclusion so the physical and virtual sources are never
active together. When the locus is `virtual` the real camera and microphone capture
are off and Topos/Audio_In consume in-world feeds; when `physical` the in-world
feeds are not consumed and `intent.avatar.*` is not forwarded. The shipped default
SHALL be `physical`.

#### Scenario: Selecting virtual disables real camera and mic

- **WHEN** the locus changes to `virtual`
- **THEN** the real camera and microphone capture are turned off in the same
  transition
- **AND** Topos and Audio_In bind to the in-world visual and chat feeds

#### Scenario: Physical locus does not perceive or act in-world

- **WHEN** the locus is `physical`
- **THEN** `intent.avatar.*` intents are not forwarded to the body
- **AND** in-world visual and chat feeds are not consumed by Topos/Audio_In

### Requirement: The operator controls and can lock the perception locus from Nexus

The operator SHALL be able to set the perception locus live from the Nexus WebUI
without restarting the entity, and SHALL be able to lock it so autonomous switching
is prevented. A locus change MUST take effect within the existing perception-state
poll interval and MUST be published as a `perception.locus.changed` event.

#### Scenario: Operator override is immediate and surfaced

- **WHEN** the operator selects a different locus in Nexus
- **THEN** the new locus takes effect within the perception-state poll interval
- **AND** a `perception.locus.changed` event records the operator-initiated switch

#### Scenario: A locked locus blocks self-switching

- **WHEN** the operator has locked the locus
- **THEN** an `intent.perception.switch` from volition is not applied
- **AND** the blocked attempt is logged

### Requirement: The entity may switch its own locus only under gated policy

The system SHALL allow volition to switch the perception locus via an
`intent.perception.switch {locus}` intent only when `[perception].allow_self_switch`
is true, and such a switch MUST be blocked by `workspace.inhibited`, rate-limited by
a minimum per-locus dwell time, audited, and reflected in the Eidolon embodiment
self-image. The shipped default for `allow_self_switch` SHALL be false.

#### Scenario: Self-switch honored when policy allows

- **WHEN** `allow_self_switch` is true, the locus is unlocked and not inhibited, and
  the minimum dwell time has elapsed
- **THEN** an `intent.perception.switch {locus: "virtual"}` moves the locus to
  virtual
- **AND** the switch is audited and the Eidolon embodiment field updates

#### Scenario: Self-switch denied by default policy

- **WHEN** `[perception].allow_self_switch` is false
- **THEN** an `intent.perception.switch` is not applied
- **AND** the denied attempt is logged and surfaced to the operator
