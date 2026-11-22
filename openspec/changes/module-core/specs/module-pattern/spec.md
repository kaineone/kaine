## ADDED Requirements

### Requirement: Modules reach shared services through a module context
Boot SHALL attach a `ModuleContext` to every module before `initialize()`, holding the cycle's entity clock, path resolution, the atomic JSON writer, a JSONL sink factory and the privacy filter. Reading `self.context` before a context is attached SHALL raise; no module SHALL receive a substitute clock.

#### Scenario: Every booted module shares the cycle's clock
- **WHEN** the registry builds every enabled module
- **THEN** each module's `self.context.clock` is the cycle's entity clock and `self.context.paths` resolves under the configured data root

#### Scenario: No silent default
- **WHEN** a module reads `self.context` before a context is attached
- **THEN** the read raises an error naming the module

#### Scenario: The context's JSONL sink strips latent fields by default
- **WHEN** a module writes a record holding a `latent` key and a nested `latent_derived` mapping through `self.context.jsonl(name)`
- **THEN** the written line holds neither key at any depth

### Requirement: Background work is started through spawn
`BaseModule.spawn` SHALL register every task it starts with the module, SHALL stop periodic work when the module stops, SHALL log a task's exception with the module and task name, and SHALL track the task for the current tick when started inside a tick.

#### Scenario: A failing background task is visible to health
- **WHEN** a task started with `spawn` raises
- **THEN** the exception is logged with the module and task name and `health()` counts the task as failed

#### Scenario: Periodic work stops with the module
- **WHEN** a module with periodic work started by `spawn(..., every_s=1.0)` is shut down
- **THEN** the work does not run again after `shutdown()` returns

### Requirement: Every module event goes through BaseModule.publish
A module SHALL publish every event through `BaseModule.publish`, which validates, stamps tick and sequence, and refreshes the heartbeat. `publish` SHALL accept `drive_oscillator=False` for events that must not drive the module's oscillator.

#### Scenario: No module publishes on the bus directly
- **WHEN** the conventions test scans `kaine/modules/`
- **THEN** no file other than `kaine/modules/base.py` calls `_bus.publish`

### Requirement: Modules report their external dependencies
A module that depends on an external service SHALL name it in `external_dependencies`, and `health()` SHALL include the module's `health_extra()` report.

#### Scenario: A dead dependency shows in health
- **WHEN** a module declares `external_dependencies = ("stt",)` and its client reports the service unreachable
- **THEN** `health()` reports the `stt` dependency as unavailable while the workspace loop is alive

### Requirement: Saved module state is versioned
`BaseModule.save_state` SHALL return `{"module", "schema_version", "state"}`. `BaseModule.load_state` SHALL accept that envelope or a bare dictionary, read as version 0, and SHALL upgrade older versions through the module's `migrate_state`. On an unknown newer version it SHALL refuse that module's restore and report it, without raising. A module with no state SHALL declare `stateless = True`.

#### Scenario: An existing bundle's bare state restores
- **WHEN** `load_state` receives a bare dictionary produced by a module's `serialize()` before this change
- **THEN** the module's observable state equals the state it had when the dictionary was produced

#### Scenario: Every registered module round-trips
- **WHEN** each registered module that is not `stateless` saves and restores its state through `json.dumps` and `json.loads`
- **THEN** each restored module's observable state equals the original
