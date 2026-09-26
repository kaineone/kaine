## ADDED Requirements

### Requirement: The package exports a kaine plugin entry point
The distribution SHALL export an entry point named `cl1` in the `kaine.plugins` group that resolves to a zero-argument callable returning the plugin object.

#### Scenario: Entry point is declared
- **WHEN** the package metadata is read
- **THEN** the `kaine.plugins` group contains `cl1 = kaine_cl1.plugin:make_plugin`

### Requirement: Seams follow the backend selection
The plugin's `seams(config)` SHALL return one seam per module set to `"cl1"` in `backends`, and SHALL raise `ValueError` naming the module when a module set to `"cl1"` has no implemented wetware backend or no channel territory. Modules absent from `backends` or set to `"silicon"` SHALL contribute no seam.

#### Scenario: Chronos on the substrate
- **WHEN** `backends = {chronos = "cl1"}` and `substrate.territories = {chronos = 12}`
- **THEN** `seams` returns `{"chronos.network"}`

#### Scenario: Unimplemented backend selected
- **WHEN** `backends = {soma = "cl1"}`
- **THEN** `seams` raises `ValueError` naming `soma`

#### Scenario: Nothing converted
- **WHEN** `backends` is empty or every module is `"silicon"`
- **THEN** `seams` returns an empty set and no substrate session is opened

### Requirement: Injections share one substrate and survive restarts
`injections("chronos", config)` SHALL return `{"network": model}` where `model` runs on the one process-wide substrate broker. A second request for the same module SHALL reuse that module's existing channel territory and SHALL NOT raise.

#### Scenario: Repeated request after a restart
- **WHEN** `injections("chronos", config)` is called three times
- **THEN** each call returns a working network on the same channels, and the broker holds exactly one territory for Chronos

#### Scenario: Unconverted module
- **WHEN** `injections("lingua", config)` is called
- **THEN** it returns an empty mapping

### Requirement: The plugin refuses a blocking real-time substrate
Until the non-blocking substrate lands, the plugin SHALL raise `ValueError` from `seams` when any module is converted and `substrate.accelerated_time` is not true.

#### Scenario: Real-time requested
- **WHEN** `backends = {chronos = "cl1"}` and `substrate.accelerated_time = false`
- **THEN** `seams` raises `ValueError` explaining that real-time substrate would block the cognitive loop

### Requirement: The plugin runs only against the simulator
The plugin SHALL raise `ValueError` from `seams` when any module is converted and `substrate.target` is not `"simulator"`. Hardware runs are a deliberate, reviewed step outside the plugin.

#### Scenario: Hardware requested with accelerated time
- **WHEN** `backends = {chronos = "cl1"}`, `substrate.target = "hardware"` and `substrate.accelerated_time = true`
- **THEN** `seams` raises `ValueError` and no substrate session is opened

### Requirement: The standalone loader reads both config forms
`load_overlay(path)` SHALL read the overlay from a file that holds it either at top level or under `[plugins.cl1]`, and SHALL raise `ValueError` for a file that holds both.

#### Scenario: Loading the shipped example
- **WHEN** `load_overlay` reads `config/kaine_cl1.example.toml`
- **THEN** the overlay converts Chronos rather than coming back empty
