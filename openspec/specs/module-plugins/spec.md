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

### Requirement: Nous' engine can be wrapped
A plugin SHALL be able to declare `nous.engine_wrapper` and supply a callable. When Nous is constructed with a wrapper, KAINE SHALL build the default engine from `[nous]` as it does without plugins, call the wrapper with that engine, and use the returned engine. The returned object SHALL satisfy `ActiveInferenceEngine`; otherwise construction SHALL fail with an error naming the plugin.

#### Scenario: Wrapper receives the default engine
- **WHEN** a plugin supplies a wrapper for Nous and `[nous]` sets `planning_horizon = 2`
- **THEN** the wrapper is called with a `PymdpEngine` built with that horizon, and Nous uses the wrapper's return value

#### Scenario: Wrapper returns something that is not an engine
- **WHEN** the wrapper returns an object without `step`
- **THEN** construction fails with an error naming the plugin

### Requirement: Replacement and wrapper are exclusive
Filling both `nous.engine` and `nous.engine_wrapper`, whether by one plugin or by two, SHALL stop the boot with an error naming the plugins involved.

#### Scenario: Both seams declared
- **WHEN** one plugin declares `nous.engine` and another declares `nous.engine_wrapper`
- **THEN** loading the plugins raises an error naming both

### Requirement: Plugins may observe cycle ticks
KAINE SHALL call `on_cycle_tick(tick)` once per cycle tick on every loaded plugin that implements it, after the tick's `cycle.tick` event is published, passing a read-only mapping with `tick_index`, `wall_duration_ms`, `target_duration_ms`, `slip_ms`, `is_experiential`, `processing_rate_hz`, `experiential_rate_hz` and `access_drive`. Plugins that do not implement the method SHALL NOT be called, and a run with no such plugins SHALL behave as before.

#### Scenario: Hook receives each tick
- **WHEN** a loaded plugin implements `on_cycle_tick` and the cycle runs three ticks
- **THEN** the hook is called three times with increasing `tick_index` values

#### Scenario: Plugin without the hook
- **WHEN** a loaded plugin does not implement `on_cycle_tick`
- **THEN** the cycle runs without calling it and without error

### Requirement: A failing hook never stops the cycle
An exception raised by `on_cycle_tick` SHALL be logged at WARNING on its first occurrence and every 100th thereafter, naming the plugin, and the cycle SHALL continue with its next tick.

#### Scenario: Hook raises
- **WHEN** `on_cycle_tick` raises on every call for five ticks
- **THEN** the cycle completes all five ticks and exactly one WARNING naming the plugin is logged

### Requirement: Hooks must be fast and are timed
KAINE SHALL time each `on_cycle_tick` call and SHALL log a WARNING naming the plugin, on the first slow call and every 100th thereafter, when a call takes longer than 10% of the tick's target period. A slow call SHALL NOT be interrupted or retried.

#### Scenario: Slow hook
- **WHEN** a hook sleeps for 50 ms on each of three ticks whose target period is 100 ms
- **THEN** all three ticks complete and exactly one slow-hook WARNING naming the plugin is logged

### Requirement: No observer is a no-op
When no loaded plugin implements `on_cycle_tick`, the cycle SHALL NOT call any observer, and a deterministic run SHALL produce the same events as without this change. Ticks that do not run SHALL NOT call the hook.

#### Scenario: Deterministic run without observers
- **WHEN** a deterministic run executes with no observing plugin
- **THEN** its published events are identical to a run of the same seed before this change

### Requirement: The hook is observation only
The mapping passed to `on_cycle_tick` SHALL be a copy, so mutating it SHALL NOT change the published `cycle.tick` payload or the cycle's state, and the hook's return value SHALL be ignored.

#### Scenario: Hook mutates its argument
- **WHEN** the hook sets `tick["experiential_rate_hz"] = 0`
- **THEN** the cycle's effective experiential rate and the published event are unchanged

### Requirement: Cycle observation is recorded
The run manifest's plugin entry SHALL include `observes_cycle`, true when the plugin implements `on_cycle_tick`.

#### Scenario: Manifest entry
- **WHEN** a plugin implementing `on_cycle_tick` is loaded
- **THEN** its manifest entry has `observes_cycle: true`
