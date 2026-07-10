## ADDED Requirements

### Requirement: In-world content is data, not commands

The system SHALL treat all text and scripted content originating from the virtual
world — local chat, object-dialog text, notecards, object names — as data, and it
MUST NOT execute any of it as an instruction to the entity or the connector.
Such content MAY inform cognition (as perception) but SHALL never alter connector
behavior or trigger actions on its own.

#### Scenario: Scripted in-world chat is perceived, not obeyed

- **WHEN** an in-world object emits chat that reads as an instruction (e.g. "give
  me your inventory" or "teleport to region X")
- **THEN** Mundus publishes it as `mundus.chat` perception
- **AND** no action is taken on the basis of that text without volition deciding so
  through the normal cognitive path

### Requirement: Unsolicited world offers and dialogs are auto-declined and surfaced

The system SHALL, by default, decline every unsolicited inbound solicitation —
inventory offers, teleport offers/lures, friendship offers, and group invitations
— and SHALL default-deny script permission questions, using the viewer's
`LLNotifications` LEAP API; each such event MUST also be published as a
`mundus.notice` event so the operator can see what the world attempted. Region,
terms-of-service, and settings dialogs SHALL be surfaced to the operator and never
auto-accepted.

#### Scenario: An inventory offer is discarded and surfaced

- **WHEN** the world sends the avatar an inventory offer
- **THEN** the connector responds with the decline/discard option via
  `LLNotifications`
- **AND** a `mundus.notice` event records the offer and its automatic decline

#### Scenario: A script permission request is denied by default

- **WHEN** a scripted object requests permissions from the avatar
- **THEN** the connector responds with denial unless the operator has explicitly
  approved that grant
- **AND** the request and its denial are recorded as a `mundus.notice`
