# cl1-substrate-plugin Specification

## Purpose
The optional biological-substrate plugin in `plugins/kaine-cl1`: how it is packaged apart from core KAINE, what it requires the operator to install, which simulator targets and data sources it accepts, and how the setup wizard offers it while keeping it off by default.

## Requirements

### Requirement: The CL1 plugin is a separate, opt-in package
The repository SHALL contain the CL1 plugin as its own distribution under `plugins/kaine-cl1/`. Installing KAINE SHALL NOT install it, and core KAINE SHALL NOT import it. It SHALL take effect only when installed and named in `[plugins].enabled`.

#### Scenario: KAINE installed without the plugin
- **WHEN** KAINE is installed and the plugin package is not
- **THEN** no `kaine_cl1` module is importable from KAINE's install and boot is unchanged

### Requirement: Cortical Labs software is pointed to, not shipped
The plugin SHALL NOT bundle or declare a dependency on `cl-sdk`. When the plugin is enabled and `cl` cannot be imported, loading SHALL fail with a message that names `pip install cl-sdk`, states the CC BY-NC 4.0 non-commercial licence, states that the simulator is non-learning and does not respond to stimulation, and states that real neurons need a Cortical Cloud account or a CL1 device.

#### Scenario: Enabled without cl-sdk
- **WHEN** `[plugins].enabled = ["cl1"]` and `cl-sdk` is not installed
- **THEN** boot raises `PluginError` whose message contains `pip install cl-sdk`, `CC BY-NC 4.0` and `non-learning`

### Requirement: Only the simulator target is accepted
The plugin SHALL accept only `target = "simulator"`. `"cloud"` and `"hardware"` SHALL stop the boot with a message explaining that remote Cortical Cloud access has no public API for external programs yet, and that hardware runs are a deliberate, reviewed step outside the plugin.

#### Scenario: Cloud requested
- **WHEN** `[plugins.cl1.substrate].target = "cloud"`
- **THEN** boot raises `PluginError` explaining that Cortical Cloud remote access is not supported yet

### Requirement: The data source is explicit and logged
The plugin SHALL read `data_source` (`"reference_culture"` by default, `"sdk"`, or `"replay"` with `replay_path`), SHALL configure the simulator accordingly, and SHALL log at WARNING at boot that the substrate is simulated, naming the data source.

#### Scenario: Default data source
- **WHEN** the plugin boots with no `data_source` set
- **THEN** the simulator uses the package's reference culture, evoked responses rise with stimulation amplitude, and the boot log names `reference_culture` and says the substrate is simulated

#### Scenario: Replay without a path
- **WHEN** `data_source = "replay"` and no `replay_path` is set
- **THEN** boot raises `PluginError` naming `replay_path`

### Requirement: The setup wizard offers the plugin, off by default
The setup wizard SHALL offer an optional CL1 step whose default answer is no and which defaults mode skips. When accepted, it SHALL show the requirements and licence note, print the install commands without running them, and write a `[plugins]` block enabling `cl1` with Chronos and Soma converted.

#### Scenario: Defaults mode
- **WHEN** the wizard runs in defaults mode
- **THEN** no `[plugins]` block is written and nothing about CL1 is installed
