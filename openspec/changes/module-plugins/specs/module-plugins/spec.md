## ADDED Requirements

### Requirement: Plugins load only when the configuration names them
KAINE SHALL discover plugins through the `kaine.plugins` entry-point group and SHALL load only plugins whose names appear in `[plugins].enabled`. An installed plugin that is not named SHALL NOT be imported. With `[plugins]` absent or `enabled` empty, boot SHALL behave exactly as it does without the plugin mechanism.

#### Scenario: Installed but not enabled
- **WHEN** a package registers a `kaine.plugins` entry point and `[plugins].enabled` does not name it
- **THEN** boot completes without importing that package and every module uses its default model

#### Scenario: No plugins section
- **WHEN** the configuration has no `[plugins]` section
- **THEN** boot constructs every module with the same arguments it uses today

### Requirement: A named plugin that cannot load stops the boot
If a plugin named in `[plugins].enabled` has no entry point, fails to import, fails to construct, or raises while supplying injections, boot SHALL raise `ConfigurationError` naming the plugin and SHALL NOT fall back to default models.

#### Scenario: Named plugin is not installed
- **WHEN** `[plugins].enabled = ["missing"]` and no entry point named `missing` exists
- **THEN** boot raises `ConfigurationError` naming `missing` before any module is constructed

### Requirement: Plugins fill only declared seams
A plugin SHALL be able to supply objects only for the seams KAINE declares: `chronos.network`, `soma.forward_model`, `nous.engine`, and the per-module oscillator. A plugin returning a key outside the declared seams, or two plugins filling the same seam, SHALL cause boot to raise `ConfigurationError`. A plugin SHALL NOT be able to enable or disable modules or change their configuration.

#### Scenario: Undeclared seam
- **WHEN** a plugin returns `{"cfc_units": 8}` for Chronos
- **THEN** boot raises `ConfigurationError` naming the plugin, the module and the key

#### Scenario: Two plugins claim one seam
- **WHEN** two enabled plugins both return an object for `chronos.network`
- **THEN** boot raises `ConfigurationError` naming both plugins

#### Scenario: Declared seam is honoured
- **WHEN** an enabled plugin returns `{"network": model}` for Chronos and Chronos is enabled
- **THEN** the constructed Chronos uses `model` as its network and builds no default CfC network

### Requirement: Substitutions survive a module restart
When Spot rebuilds a module on its heavy-restart path, the rebuilt module SHALL receive plugin injections the same way `build_registry` supplies them.

#### Scenario: Chronos restarted under a plugin
- **WHEN** Chronos was built with a plugin-supplied network and Spot rebuilds it
- **THEN** the rebuilt Chronos uses a network supplied by the same plugin, not the default CfC network

### Requirement: Substitutions are recorded
Boot SHALL log each filled seam at WARNING level, and the run manifest SHALL record, for each enabled plugin, its name, its version and the seams it filled.

#### Scenario: Manifest of a substituted run
- **WHEN** a run boots with a plugin that fills `chronos.network`
- **THEN** the run manifest's `plugins` entry lists that plugin's name, version and `chronos.network`

### Requirement: Plugin configuration is namespaced
Each plugin SHALL receive only its own `[plugins.<name>]` table. Configuration shape validation SHALL reject a `plugins.enabled` value that is not a list of strings.

#### Scenario: Malformed enabled list
- **WHEN** `[plugins].enabled = "cl"`
- **THEN** configuration validation raises `ConfigShapeError` naming `plugins.enabled`
