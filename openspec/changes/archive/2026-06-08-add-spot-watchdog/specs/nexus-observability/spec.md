## ADDED Requirements

### Requirement: Supervisor incident status on the health surface
The Nexus health snapshot SHALL include a `spot` block reporting the supervisor
incident state — `ok`, `recovery`, or `critical` — derived from the freeze control
(`frozen` and `source == "spot"` ⇒ `recovery`) and the escalation record
(`escalated` ⇒ `critical`), together with the affected `module`, `attempts`,
`max_attempts`, an operator `message`, and the saved `snapshot_id` when present.
The block SHALL contain only operational data (no sensory content) and SHALL be
served on `/diagnostics/health.json` so a freshly loaded or reconnected page paints
the correct state.

#### Scenario: Recovery state surfaced
- **WHEN** the freeze control is frozen with `source == "spot"` and no escalation
  is recorded
- **THEN** the health snapshot's `spot.state` is `"recovery"`

#### Scenario: Critical state surfaced
- **WHEN** an escalation record exists
- **THEN** the health snapshot's `spot.state` is `"critical"` and carries the
  operator message and `snapshot_id`

#### Scenario: Default ok state
- **WHEN** there is no Spot freeze and no escalation
- **THEN** the health snapshot's `spot.state` is `"ok"`

### Requirement: Operator alert UI for supervisor incidents
The diagnostics UI SHALL render a full-window alert border that turns yellow during
a `recovery` state and red during a `critical` state, a status banner carrying the
human message, and a live incident console fed by the `spot.out` bus stream
(`spot.status` flips the border/banner; `spot.log` lines append to the console).
`spot.out` SHALL be included in the diagnostics SSE streams. Any pulse animation on
the alert border SHALL be disabled under `prefers-reduced-motion`.

#### Scenario: Border reflects incident state
- **WHEN** the health snapshot reports `spot.state == "critical"`
- **THEN** the page renders the alert border in its red (critical) state

#### Scenario: Live console receives incident lines
- **WHEN** Spot publishes `spot.log` events during an incident
- **THEN** the diagnostics page appends those lines to the incident console via the
  SSE stream

#### Scenario: Reduced motion disables the pulse
- **WHEN** the operator's environment requests reduced motion
- **THEN** the alert border is shown without a pulsing animation
