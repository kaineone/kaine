# module-plugins Specification

## Purpose
How an out-of-tree package substitutes the model inside a cognitive module without forking KAINE: plugins load only when the configuration names them, fill only seams KAINE declares, stop the boot when they cannot load or supply their seams, keep their substitutions across restarts, and are recorded in the run manifest.

## Requirements

### Requirement: Plugins load only when the configuration names them
KAINE SHALL discover plugins through the `kaine.plugins` entry-point group and SHALL load only plugins whose names appear in `[plugins].enabled`. An installed plugin that is not named SHALL NOT be imported. With `[plugins]` absent or `enabled` empty, boot SHALL behave exactly as it does without the plugin mechanism.

#### Scenario: Installed but not enabled
- **WHEN** a package registers a `kaine.plugins` entry point and `[plugins].enabled` does not name it
- **THEN** boot completes without importing that package and every module uses its default model

#### Scenario: No plugins section
- **WHEN** the configuration has no `[plugins]` section
- **THEN** boot constructs every module with the same arguments it uses today

### Requirement: A named plugin that cannot load stops the boot
If a plugin named in `[plugins].enabled` has no entry point, is exported by more than one installed distribution, fails to import, fails to construct, or raises while declaring its seams or supplying injections, boot SHALL raise `PluginError` naming the plugin and SHALL NOT fall back to default models.

#### Scenario: Named plugin is not installed
- **WHEN** `[plugins].enabled = ["missing"]` and no entry point named `missing` exists
- **THEN** boot raises `PluginError` naming `missing` before any module is constructed

### Requirement: Plugins fill only declared seams
A plugin SHALL declare its seams when it is loaded, and SHALL be able to fill only seams KAINE declares: `chronos.network`, `soma.forward_model`, `nous.engine`, and `oscillator.<module>`. A plugin declaring an unknown seam, two plugins declaring the same seam, or a plugin returning a seam it did not declare SHALL cause boot to raise `PluginError`. Seam validation and conflict detection SHALL happen before any module is constructed. A plugin SHALL NOT be able to enable or disable modules, switch on the oscillator layer, or change configuration.

#### Scenario: Unknown seam
- **WHEN** a plugin declares `chronos.cfc_units`
- **THEN** boot raises `PluginError` naming the plugin and the seam before any module is constructed

#### Scenario: Returned seam was not declared
- **WHEN** a plugin declared only `chronos.network` and its `injections` for Soma returns `{"forward_model": model}`
- **THEN** boot raises `PluginError` naming the plugin, the module and the key

#### Scenario: Two plugins claim one seam
- **WHEN** two enabled plugins both declare `chronos.network`
- **THEN** boot raises `PluginError` naming both plugins before any module is constructed

#### Scenario: Oscillator seam with the layer off
- **WHEN** a plugin declares `oscillator.chronos` and `[oscillator].enabled` is false
- **THEN** boot raises `PluginError` naming the plugin and the seam

#### Scenario: Declared seam is honoured
- **WHEN** an enabled plugin returns `{"network": model}` for Chronos and Chronos is enabled
- **THEN** the constructed Chronos uses `model` as its network and builds no default CfC network

### Requirement: Substitutions survive a module restart
When Spot rebuilds a module on its heavy-restart path, the rebuilt module SHALL receive plugin injections the same way `build_registry` supplies them.

#### Scenario: Chronos restarted under a plugin
- **WHEN** Chronos was built with a plugin-supplied network and Spot rebuilds it
- **THEN** the rebuilt Chronos uses a network supplied by the same plugin, not the default CfC network

### Requirement: Substitutions are recorded
Boot SHALL log each filled seam at WARNING level, and the run manifest SHALL record, for each enabled plugin, its name, the distribution name and version from package metadata, and its declared seams. The manifest entry SHALL be complete when the manifest is written, which happens before modules are constructed.

#### Scenario: Manifest of a substituted run
- **WHEN** a run boots with a plugin that fills `chronos.network`
- **THEN** the run manifest's `plugins` entry lists that plugin's name, its distribution and version, and `chronos.network`

### Requirement: Plugin configuration is namespaced
Each plugin SHALL receive only its own `[plugins.<name>]` table. Configuration shape validation SHALL reject a `plugins.enabled` value that is not a list of strings.

#### Scenario: Malformed enabled list
- **WHEN** `[plugins].enabled = "cl"`
- **THEN** configuration validation raises `ConfigShapeError` naming `plugins.enabled`
