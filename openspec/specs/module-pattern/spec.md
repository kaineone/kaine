# module-pattern Specification

## Purpose
TBD - created by archiving change module-pattern. Update Purpose after archive.
## Requirements
### Requirement: BaseModule lifecycle contract
`BaseModule` SHALL define the lifecycle hooks `initialize`, `shutdown`,
`publish`, `on_workspace`, `serialize`, `deserialize` as async methods.
Subclasses SHALL declare a class-level `name: ClassVar[str]` matching
the module's bus output stream prefix. `BaseModule.publish` SHALL build
a valid `Event` with `source = self.name` and publish it through the
attached `AsyncBus`.

#### Scenario: Subclass without name fails fast
- **WHEN** a subclass of `BaseModule` without `name` is instantiated
- **THEN** instantiation raises `TypeError`

#### Scenario: publish routes to the module's stream
- **WHEN** a module named `echo` calls `self.publish("test.type", {"v": 1}, salience=0.5)`
- **THEN** an event with `source="echo"` is added to the `echo.out`
  stream

### Requirement: BaseModule consumes workspace broadcasts
`BaseModule.initialize` SHALL start a background task subscribing to
`workspace.broadcast` and invoke `on_workspace(snapshot)` for each
broadcast, where `snapshot` is a reconstructed `WorkspaceSnapshot`
including `selected_events` as `(entry_id, Event)` tuples. Subclasses
SHALL override `on_workspace`. Exceptions raised by `on_workspace`
SHALL be logged but SHALL NOT stop the background task.

#### Scenario: on_workspace fires for each broadcast
- **WHEN** the cycle publishes three experiential broadcasts to
  `workspace.broadcast` while a module is initialized
- **THEN** the module's `on_workspace` is invoked three times in
  broadcast order

#### Scenario: on_workspace error does not stop subscription
- **WHEN** a module's `on_workspace` raises for the second broadcast
- **THEN** the module's `on_workspace` is still invoked for the third
  broadcast

### Requirement: Module state serialization
`BaseModule.serialize` SHALL return a JSON-serializable dict and
`BaseModule.deserialize` SHALL accept the same shape and restore the
module's state. The base implementation SHALL return `{}` and accept
`{}` so subclasses with no state need not override either method.

#### Scenario: Roundtrip preserves subclass state
- **WHEN** a subclass overrides serialize/deserialize and round-trips
  its state through `json.loads(json.dumps(module.serialize()))`
- **THEN** `module2.deserialize(state)` produces a module whose
  observable state equals the original

### Requirement: ModuleRegistry satisfies the cycle's protocol
`ModuleRegistry` SHALL implement
`kaine.cycle.protocols.ModuleRegistryProtocol`. `active_streams()`
SHALL return `<module_name>.out` for every currently registered
module. `register(module)` and `unregister(name)` SHALL update the
registry such that the next call to `active_streams()` reflects the
change.

#### Scenario: Registered module appears in active_streams
- **WHEN** a module named `chronos` is registered with the registry
- **THEN** `registry.active_streams()` contains `"chronos.out"`

#### Scenario: Unregistered module disappears
- **WHEN** `registry.unregister("chronos")` is called
- **THEN** `registry.active_streams()` no longer contains `"chronos.out"`

#### Scenario: Duplicate registration rejected
- **WHEN** a module is registered twice under the same name
- **THEN** the second `register` call raises `ValueError`

### Requirement: EchoModule end-to-end canary
`EchoModule` SHALL be a `BaseModule` subclass that records every
workspace snapshot it observes in a list accessible as
`module.snapshots`. The Phase 1 end-to-end integration test SHALL
publish one event, run one cycle tick, and assert that EchoModule's
`snapshots` contains a snapshot whose `selected_events` includes the
published event.

#### Scenario: End-to-end wiring delivers a published event
- **WHEN** an event is published to the bus, the cycle runs one
  experiential tick, and the cycle invokes Syneidesis with that event
- **THEN** EchoModule's `snapshots` eventually contains a snapshot
  whose `selected_events` includes that event's `(entry_id, Event)`
  tuple

### Requirement: BaseModule liveness and restart contract
`BaseModule` SHALL maintain a monotonic heartbeat that is refreshed centrally —
after each `on_workspace` in the workspace loop and at the end of `publish` — so
that any initialized module receiving the workspace broadcast keeps a fresh
heartbeat regardless of its own publishing activity. `BaseModule` SHALL expose
`heartbeat_age() -> float` (seconds since the last beat) and `health() -> dict`
reporting at least `name`, `heartbeat_age_s`, `tasks_total`, `tasks_done`, and
`tasks_failed`, derived from its task list; `health()` SHALL NOT raise.
`BaseModule` SHALL expose an async `restart()` that tears down and recreates the
module's own tasks (a light restart), and `holds_external_resources() -> bool`
(default `False`) that a subclass overrides to signal it must be rebuilt rather
than light-restarted.

#### Scenario: Heartbeat refreshes on broadcast and publish
- **WHEN** a module handles a workspace broadcast or publishes an event
- **THEN** its `heartbeat_age()` drops toward zero

#### Scenario: Health snapshot reports task state
- **WHEN** `health()` is called on a module with a crashed task
- **THEN** the returned dict reports `tasks_failed >= 1` and does not raise

#### Scenario: Default modules are light-restartable
- **WHEN** a module that has not overridden `holds_external_resources()` is asked
  for it
- **THEN** the result is `False` and `restart()` recreates its tasks

#### Scenario: Resource-holding modules opt into heavy restart
- **WHEN** a module that constructs external clients or model handles is asked for
  `holds_external_resources()`
- **THEN** the result is `True`

### Requirement: ModuleRegistry instance replacement
`ModuleRegistry` SHALL expose `replace(name, module)` that swaps the instance
registered under `name` for a new one whose `name` matches, so a supervisor can
substitute a freshly rebuilt module without re-registering. It SHALL raise if the
name is not present or the replacement's `name` differs.

#### Scenario: Replace swaps the instance
- **WHEN** `replace("mnemos", new_mnemos)` is called and a `mnemos` is registered
- **THEN** `get("mnemos")` returns the new instance

#### Scenario: Replace rejects a name mismatch
- **WHEN** `replace("mnemos", a_vox_instance)` is called
- **THEN** it raises rather than registering a mismatched instance

