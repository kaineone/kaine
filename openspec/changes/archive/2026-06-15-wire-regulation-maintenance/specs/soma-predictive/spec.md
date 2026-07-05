## MODIFIED Requirements

### Requirement: Cycle engine drains soma.regulation advisorily
The cognitive cycle engine SHALL subscribe to the `soma.out` stream and drain
`soma.regulation` events, acting on the `action` field in an advisory capacity:
`reduce_rate` MUST lower the current tick rate within configured bounds,
`shed_module` MUST request a low-priority module suspension, and
`request_maintenance` MUST latch an advisory `maintenance_requested` flag for
diagnostics. The early-maintenance trigger SHALL be event-driven and SHALL NOT
depend on that flag: Hypnos, observing the `soma.regulation` /
`request_maintenance` event directly on `soma.out`, SHALL schedule an earlier
offline maintenance cycle. The cycle SHALL log each advisory action and SHALL
NOT raise an exception on an unrecognized `action` value.

#### Scenario: reduce_rate slows the cycle
- **WHEN** the cycle engine receives a `soma.regulation` event with `action == "reduce_rate"`
- **THEN** the cycle's current tick interval is increased (rate decreased) within its configured bounds

#### Scenario: request_maintenance flags Hypnos
- **WHEN** a `soma.regulation` event with `action == "request_maintenance"` is published on `soma.out`
- **THEN** the cycle engine latches its advisory `maintenance_requested` flag to `true` for diagnostics
- **AND** Hypnos, observing that same `soma.regulation` / `request_maintenance` event on `soma.out`, schedules an earlier offline maintenance cycle through its guarded sleep path
