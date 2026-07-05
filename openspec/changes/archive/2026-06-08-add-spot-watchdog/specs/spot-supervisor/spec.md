## ADDED Requirements

### Requirement: Always-on module supervisor
The cycle entrypoint SHALL run a supervisor component (Spot) as a task alongside
`cycle.run_forever`, when `[spot].enabled` is true. Spot SHALL NOT be a registered
module (it must act when modules fail and cannot watch itself). On each poll
(default `poll_interval_s = 2.0`) Spot SHALL assess every registered module's
liveness and drive recovery for at most one incident at a time. Spot SHALL ship
disabled by default.

#### Scenario: Disabled by default
- **WHEN** `config/kaine.toml` is loaded as shipped
- **THEN** `[spot].enabled` is `false` and no supervisor task runs

#### Scenario: Supervisor runs when enabled
- **WHEN** the cycle entrypoint boots with `[spot].enabled = true`
- **THEN** a Spot task is created next to the cycle and freeze-watch tasks and is
  awaited during shutdown

### Requirement: Module liveness detection
Spot SHALL classify each module as `alive`, `dead`, or `hung`. A module SHALL be
`dead` when any of its tasks finished with an exception, or returned while the
module was not stopping (an organ loop that exited on its own). A module SHALL be
`hung` only when its heartbeat age exceeds the configured timeout AND at least one
task is still running AND the entity is not in maintenance sleep. A module that is
merely quiet (no recent output but tasks running and heartbeat fresh) SHALL be
`alive`. When the registry's `hypnos` reports `is_sleeping`, hang flags SHALL be
suppressed (the crash signal still applies).

#### Scenario: Crashed task is dead
- **WHEN** a module's task has finished with an exception
- **THEN** Spot classifies that module as `dead`

#### Scenario: Quiet but live module is alive
- **WHEN** a module has published nothing recently but its tasks are running and
  its heartbeat is fresh
- **THEN** Spot classifies it as `alive` and takes no recovery action

#### Scenario: Sleep suppresses hang flags
- **WHEN** `hypnos.is_sleeping` is true and a module's heartbeat is stale
- **THEN** Spot does not classify that module as `hung`

### Requirement: Freeze the entity during recovery
On detecting a failed module Spot SHALL freeze the entity by writing the
operator-freeze control with `source = "spot"`, so the existing freeze-watch loop
pauses the cycle and halts perception. Spot SHALL resume (clear the freeze) only
when the control's `source` is `"spot"`, and SHALL never clear an operator freeze.
When the control is already frozen with `source = "operator"`, Spot SHALL take no
recovery action.

#### Scenario: Spot freeze halts the entity
- **WHEN** Spot detects a `dead` module
- **THEN** it writes the freeze control with `source = "spot"` before attempting
  restart

#### Scenario: Spot does not clear an operator freeze
- **WHEN** the freeze control is frozen with `source = "operator"`
- **THEN** Spot performs no recovery and does not modify the control

### Requirement: Snapshot before restart and at escalation
Spot SHALL take a last-good `ForkManager` snapshot before the first restart attempt
of an incident, and a final snapshot at escalation. Snapshots SHALL contain only
each module's `serialize()` output (numeric/derived state); no raw sensory data.

#### Scenario: Pre-restart snapshot
- **WHEN** Spot begins recovery for a module (attempt count 0)
- **THEN** it records a snapshot labeled for that module before the first restart

#### Scenario: Escalation snapshot
- **WHEN** Spot reaches the maximum restart attempts
- **THEN** it records a final snapshot before shutting modules down

### Requirement: Restart ladder
Spot SHALL attempt a light restart (recreate the module's own tasks via
`BaseModule.restart`) for modules that hold no external resources, and a heavy
rebuild (reconstruct via the boot factory, swap via `ModuleRegistry.replace`,
re-run post-build wiring, then `ForkManager.restore` the last-good state) for
modules whose `holds_external_resources()` is true. A heavy rebuild SHALL shut the
old instance down before constructing the new one, and SHALL re-fetch any sibling
references (e.g. Hypnos's mnemos/thymos/phantasia) from the registry.

#### Scenario: Light restart for a pure module
- **WHEN** Spot restarts a module whose `holds_external_resources()` is false
- **THEN** it calls the module's `restart()` and re-assesses liveness

#### Scenario: Heavy rebuild for a resource-holding module
- **WHEN** Spot restarts a module whose `holds_external_resources()` is true
- **THEN** it shuts the old instance down, builds a fresh instance via the boot
  factory, swaps it in via `ModuleRegistry.replace`, re-runs post-build wiring, and
  restores the last-good snapshot into it

### Requirement: Escalation after repeated failures
Spot SHALL escalate after `max_restart_attempts` (default 5) failed restarts of the
same module in one incident. Escalation SHALL take a final snapshot, shut down all
modules cleanly, write `state/cycle/escalation.json` with operational fields only
(`escalated`, `module`, `attempts`, `snapshot_id`, `escalated_at`, operator
`message`), and cause the cycle process to exit non-zero so it does not auto-retry.
Spot SHALL NOT reboot the machine; the escalation message SHALL instruct the
operator to reboot and restart. A clean boot SHALL clear any prior escalation
record.

#### Scenario: Five failures escalate
- **WHEN** a module fails restart five times in one incident
- **THEN** Spot writes `escalation.json`, shuts down all modules, and signals a
  non-zero process exit

#### Scenario: Escalation does not auto-retry
- **WHEN** Spot has escalated
- **THEN** the process exits and does not itself restart the modules or the machine

#### Scenario: Clean boot clears escalation
- **WHEN** the cycle entrypoint starts cleanly
- **THEN** any existing `escalation.json` is cleared

### Requirement: Incident events on the bus
Spot SHALL publish incident events to a `spot.out` stream: `spot.status` events
carrying the current state (`ok` | `recovery` | `critical`) with the affected
module, attempt count, and a human message; and `spot.log` events carrying a
level and a human-readable line as the incident progresses. These events SHALL
contain only operational data (no sensory content) so the Nexus diagnostics stream
can fan them out.

#### Scenario: Recovery publishes status and log
- **WHEN** Spot begins recovering a module
- **THEN** it publishes a `spot.status` event with state `recovery` and one or more
  `spot.log` events describing the attempt
