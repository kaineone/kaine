## ADDED Requirements

### Requirement: Every study step runs the module supervisor
`build_overlay` SHALL set `[supervisor].enabled = true` and `[supervisor.incident_log].enabled = true` for every step kind, overriding the operator config, with the incident log path relative to the step's working directory. A test SHALL build the merged config of each step kind (shipped config plus study overlay, no operator overlay) and assert that every config-level research-gate requirement, including the supervisor's, passes.

#### Scenario: An operator config turns the supervisor off
- **WHEN** the operator config sets `[supervisor].enabled = false`
- **THEN** every step's overlay sets it to true

#### Scenario: The incident log stays inside the step
- **WHEN** an overlay is built for branch step 3
- **THEN** the incident log path resolves inside that step's directory

### Requirement: A supervisor escalation is its own step outcome
After a step's cycle exits, the study runner SHALL read the step's `state/cycle/escalation.json`. When it exists, the step's outcome SHALL be `failed:supervisor`, the record SHALL carry the escalation record's content-free fields, and the study SHALL halt for the operator. A step that completes SHALL record `supervisor_restarts`, the number of restart transitions in the step's incident log, and the analysis SHALL list viewings with at least one restart.

#### Scenario: A step escalates
- **WHEN** the supervisor escalates during a viewing and the cycle exits non-zero
- **THEN** the step is recorded as `failed:supervisor`, not `failed:exit:<code>`, and the next step does not start

#### Scenario: A restart that recovered
- **WHEN** the supervisor restarted one module once during a viewing and the step completed
- **THEN** the step record carries `supervisor_restarts: 1` and the viewing is listed as having a restart
