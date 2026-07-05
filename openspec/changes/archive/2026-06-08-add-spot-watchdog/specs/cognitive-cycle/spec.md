## ADDED Requirements

### Requirement: Freeze control attribution
The cycle freeze control SHALL carry a `source` field identifying who froze the
entity — `"operator"` (the default, written by the Nexus freeze endpoint) or
`"spot"` (written by the supervisor during recovery). Reading a control file with
no `source` SHALL default to `"operator"` (backward compatible). The freeze-watch
loop SHALL pause/resume the cycle on the `frozen` flag regardless of source.

#### Scenario: Operator freeze defaults the source
- **WHEN** the operator freezes via the Nexus endpoint
- **THEN** the control records `source = "operator"`

#### Scenario: Legacy control without source reads as operator
- **WHEN** an existing control file without a `source` field is read
- **THEN** the parsed source is `"operator"`

### Requirement: Supervisor lifecycle and escalation exit
When `[spot].enabled` is true the cycle entrypoint SHALL construct a `ForkManager`
and a module-rebuild closure, parse `[spot]`, construct the supervisor, run it as a
task alongside the cycle and freeze-watch tasks, and await it during shutdown. The
entrypoint SHALL clear any stale escalation record at clean boot (next to the
existing freeze clear) and SHALL propagate a non-zero process exit when the
supervisor escalates, so an escalated run does not appear successful.

#### Scenario: Clean boot clears stale escalation
- **WHEN** the cycle entrypoint starts
- **THEN** any prior `escalation.json` is cleared before the cycle runs

#### Scenario: Escalation yields a non-zero exit
- **WHEN** the supervisor escalates during a run
- **THEN** the entrypoint returns a non-zero exit code after shutting down
