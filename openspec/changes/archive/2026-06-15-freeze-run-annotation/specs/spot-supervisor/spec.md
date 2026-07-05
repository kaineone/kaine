# spot-supervisor (delta)

## ADDED Requirements

### Requirement: Structured incident bus event per lifecycle transition

Spot SHALL publish a structured `spot.incident` bus event at each lifecycle
transition (detect, freeze, snapshot, restart, escalate), IN ADDITION to — and
never in place of — the existing ephemeral `spot.status` / `spot.log` events and
the durable `state/cycle/incidents/` log. The event SHALL be published via Spot's
existing bus publish path with `source = "spot"` and `type = "spot.incident"`,
and SHALL carry the incident's `incident_id`, the `transition`, the affected
`module`, the fault metadata (`fault_class` for detect; `fault_type` for freeze),
the transition-specific operational fields already recorded in the durable
incident record (freeze reason; snapshot id/byte size; restart path / outcome /
latency / restored-checkpoint flag; escalate attempts / outcome / final snapshot
id), and a cycle position. The cycle position SHALL always include Spot's
`poll_index` and SHALL include the cycle's `tick_index` when a tick-index
provider is available to Spot (a best-effort callable wired at construction); a
`tick_index` SHALL NOT be fabricated when no provider is available. Any free-text
field SHALL be scrubbed of operator filesystem paths (the same scrubber used by
the durable incident log) before publish. The durable incident log and the
`spot.status` / `spot.log` events SHALL remain unchanged by this requirement.

#### Scenario: Incident event published at each transition

- **WHEN** a `dead` module is detected, frozen, snapshotted, and restarted in one
  poll
- **THEN** Spot publishes a `spot.incident` event with `source = "spot"` for the
  `detect`, `freeze`, `snapshot`, and `restart` transitions, each carrying the
  same `incident_id`, the `module`, and the transition-specific fields

#### Scenario: Ephemeral status/log events are still published

- **WHEN** Spot handles an incident
- **THEN** the existing `spot.status` and `spot.log` events are still published
  alongside the new `spot.incident` events (none is replaced)

#### Scenario: Cycle position is included

- **WHEN** Spot is constructed with a tick-index provider and publishes a
  `spot.incident` event
- **THEN** the event payload carries `poll_index` and a `tick_index` read from
  the provider
- **AND WHEN** no tick-index provider is available
- **THEN** the event payload carries `poll_index` and no fabricated `tick_index`

#### Scenario: Operator paths are scrubbed

- **WHEN** a detect event is published for a module whose crash exception repr
  contains an operator filesystem path
- **THEN** the published `spot.incident` payload contains `<PATH>` and never the
  raw path

### Requirement: Run-level freeze annotation in the research event log

The research event log SHALL capture `spot.incident` bus events (and the
`spot.incident.*` subtype family) into privacy-filtered records under the
export-eligible `data/evaluation/research_events/` directory, so that a run whose
data was collected across a Spot freeze carries the annotation. Each captured
record SHALL carry the `incident_id` (joining it to the durable incident
provenance) and SHALL be stamped with the active run's `run_id` (joining it to
the run) when a run context is set. The record SHALL include only the allowlisted
operational fields of the incident event (transition, module, fault metadata,
snapshot id, restart outcome/path/latency, escalate outcome, cycle position) and
SHALL NOT include any content field.

#### Scenario: Incident recorded with incident_id and run_id

- **WHEN** the research observer reads a `spot.incident` event carrying an
  `incident_id` while a run context is set
- **THEN** it writes one research-event record carrying that `incident_id` and
  the run's `run_id`

#### Scenario: Incident recorded without a run context

- **WHEN** the research observer reads a `spot.incident` event and no run context
  is set
- **THEN** it still writes the record with the `incident_id`, and no `run_id` is
  added

#### Scenario: Operational fields kept, content dropped

- **WHEN** the research observer records a `spot.incident` event
- **THEN** the record carries the allowlisted operational fields and no content
  field (per the observer's allowlist-by-construction privacy filter)
