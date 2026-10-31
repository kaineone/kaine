## ADDED Requirements

### Requirement: An adapter declares whether it is a reference body

`EmbodimentCapabilities` SHALL carry `reference: bool`, defaulting to false. The stub adapter SHALL declare `reference = True`.

#### Scenario: The stub is a reference body

- **WHEN** `StubAdapter().capabilities()` is read
- **THEN** `reference` is true

### Requirement: Configuration never builds a reference body

The embodiment factory SHALL refuse to build an adapter that declares `reference = True`, and SHALL treat `[embodiment].adapter = "none"` the same way, with a boot refusal stating that no body adapter is built. The shipped configuration SHALL set `[embodiment].adapter = "none"`.

#### Scenario: Enabling embodiment with the stub refuses the boot

- **WHEN** `[modules].embodiment = true` and `[embodiment].adapter = "stub"`
- **THEN** the boot refuses with a message that embodiment is held and no body adapter is built

#### Scenario: The shipped adapter is none

- **WHEN** the shipped `config/kaine.toml` is read
- **THEN** `[embodiment].adapter` is `"none"`

### Requirement: A reference body is never reachable and never forwards

`probe_available()` SHALL return false for a reference adapter. The `forwarded` field of an `embodiment.efference` event SHALL be true only when a non-reference adapter accepted the command.

#### Scenario: Maturation does not count a reference body

- **WHEN** an embodiment module built directly with a reference adapter is in the registry and the maturation gate asks whether the body is reachable
- **THEN** the gate sees an unreachable body and does not enter the `embodied` stage on its account

#### Scenario: No forwarded efference from a reference body

- **WHEN** a continuous command is routed to a reference adapter
- **THEN** the published efference copy has `forwarded == false`

### Requirement: The control surface cannot be enabled without a driving loop

Config validation SHALL refuse `[embodiment.control_surface].enabled = true` while no motor-seam driver is registered, with an error naming the missing loop.

#### Scenario: Enabled surface without a loop

- **WHEN** `[embodiment.control_surface].enabled = true` and no motor-seam driver is registered
- **THEN** configuration validation fails naming the missing driving loop

### Requirement: Every status surface reads one derived build status

`embodiment_built()` SHALL return true only when a non-reference adapter is registered in the factory and a motor-seam driver is registered. While it is false, the wizard SHALL NOT offer the embodiment module, the dashboard health page SHALL show embodiment as held and not built, and the module-addition study's `init` SHALL refuse an order that names embodiment.

#### Scenario: Study init refuses embodiment while not built

- **WHEN** `init --order embodiment` runs and `embodiment_built()` is false
- **THEN** `init` exits non-zero and names the held status

#### Scenario: The wizard hides the toggle

- **WHEN** the wizard's module step runs and `embodiment_built()` is false
- **THEN** no embodiment toggle is offered and the step states that embodiment is held
