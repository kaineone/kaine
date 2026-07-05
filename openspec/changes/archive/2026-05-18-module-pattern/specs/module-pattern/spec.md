## ADDED Requirements

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
