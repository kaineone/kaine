## ADDED Requirements

### Requirement: Every direct coupling between modules is declared

The repository SHALL hold one inventory, `kaine/boot/couplings.py`, of every direct call that boot or the cycle makes on a module object, and of every callable or shared object handed to a module. Each record SHALL give the coupling's name, kind (`boot_configuration`, `per_tick_read`, `command`, `time_critical`, `observation_read`), caller, callee module, method, protocol and reason.

#### Scenario: The inventory names the affective reset

- **WHEN** the inventory is read
- **THEN** it holds a record for the sleep module's affective reset with kind `command` and callee module `affect`

### Requirement: An undeclared direct coupling fails CI

A test SHALL walk `kaine/boot/` and `kaine/cycle/` and SHALL fail on any call to a method of an object obtained from the module registry that the inventory does not declare, on any non-literal `getattr` of such an object, and on any inventory record the code no longer makes.

#### Scenario: A new setter call fails the pin test

- **WHEN** boot code adds `registry.get("affect").set_new_thing(...)` without an inventory record
- **THEN** `tests/test_control_coupling_inventory.py` fails and names the call site

#### Scenario: A removed coupling fails the pin test

- **WHEN** an inventory record names a call the code no longer makes
- **THEN** the pin test fails and names the stale record

### Requirement: Each declared coupling has a typed protocol

Every inventory record SHALL name a `typing.Protocol` that states the methods and signatures the callee module provides for that coupling. A module SHALL be usable in the cycle when it implements the protocols of the couplings that name it and the bus contracts of its events.

#### Scenario: A replacement affect module needs only the declared protocols

- **WHEN** a test affect module implements only the protocols the inventory names for `affect` and publishes conforming `affect.state` events
- **THEN** boot wires it and the cycle runs a tick without an attribute error

### Requirement: Arousal is read through one read-only protocol

The workspace's state modulator and the vision and audition modules SHALL receive an `ArousalSource` with a single method `arousal() -> float`, and SHALL NOT receive the affect module object. The protocol SHALL be declared `per_tick_read` with the reason that `affect.state` is published at most once per publish interval.

#### Scenario: Same arousal on the same tick

- **WHEN** the cycle runs a recorded tick sequence before and after the `ArousalSource` refactor
- **THEN** the modulator gain and the aperture sizes on every tick are identical

### Requirement: The speaking gate is declared time-critical

The shared speaking gate between the vocal and audition modules SHALL be declared with kind `time_critical` and the reason that self-voice suppression acts within one audio window, after corollary discharge (Crapse and Sommer 2008).

#### Scenario: The gate record carries its reason

- **WHEN** the inventory record for the speaking gate is read
- **THEN** its kind is `time_critical` and its reason cites corollary discharge

### Requirement: The interfaces page is generated from the inventory

The documentation SHALL include an interfaces page generated from the inventory, listing every coupling with its kind and reason, and stating that the workspace broadcast is a separate record type with a source and timestamp and no intensity or causal parent.

#### Scenario: Docs match the inventory

- **WHEN** the docs generator runs on the inventory
- **THEN** the committed interfaces page is unchanged, or the docs check fails
