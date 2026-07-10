## ADDED Requirements

### Requirement: Avatar intents map to LEAP ops with safest-first effector gating

The system SHALL forward `intent.avatar.*` intents from `volition.out` to the
viewer as LEAP ops, and each action family MUST be individually gated by a
`[mundus].expose_<family>` flag whose shipped default is restrictive: only
`move`, `turn`, `say`, `sit_on`, `stand`, `animate`, and `gesture` default on;
`teleport` and `touch` default off and require operator opt-in.

Mundus SHALL reuse the world-agnostic `intent.avatar.{move,turn,say,sleep,wake}`
family defined by the Paracosm connector where semantics align, and SHALL add the
OpenSim-native verbs `teleport`, `sit_on`, `stand`, `touch`, `animate`, and
`gesture`. The connector SHALL NOT expose any action for rezzing/creating objects,
editing terrain, transferring or accepting inventory, any economy or fund-transfer
action, running scripts, or attaching/detaching — these have no intent and are not
forwarded. Continuous locomotion SHALL be held by the shim between cognitive ticks
(goal-based autopilot or held synthetic input), not issued per tick by the cycle.

#### Scenario: A gated-off effector is dropped with an audit entry

- **WHEN** volition emits `intent.avatar.teleport` while `[mundus].expose_teleport`
  is false
- **THEN** Mundus does not forward the op
- **AND** the rejection is recorded in the action audit

#### Scenario: An exposed action reaches the viewer and reports its result

- **WHEN** volition emits `intent.avatar.say` with the `say` family exposed
- **THEN** the shim invokes the viewer's `LLChatBar.sendChat` op
- **AND** the op's success or failure is published as `mundus.action.result`

#### Scenario: Inhibition pauses the embodied agent

- **WHEN** `workspace.inhibited` is true
- **THEN** no `intent.avatar.*` intents are forwarded to the viewer
- **AND** the bridge connection remains open so the avatar stays in-world
