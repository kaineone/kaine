## MODIFIED Requirements

### Requirement: Plugins fill only declared seams
A plugin SHALL declare its seams when it is loaded and SHALL fill only seams KAINE declares: `sequence.network`, `interoception.forward_model`, `planning.engine`, `planning.engine_wrapper`, `audition.acoustic_encoder`, `workspace.salience`, `workspace.access`, `workspace.context` and `oscillator.<module>`. An unknown seam, two plugins declaring one seam, or a returned seam that was not declared SHALL raise `PluginError` before any module or the workspace is constructed. A plugin SHALL NOT enable or disable modules, switch on the oscillator layer, or change configuration.

#### Scenario: Unknown seam
- **WHEN** a plugin declares `sequence.cfc_units`
- **THEN** boot raises `PluginError` naming the plugin and the seam before any module is constructed

#### Scenario: Returned seam was not declared
- **WHEN** a plugin declared only `sequence.network` and its `injections` for the interoception module returns `{"forward_model": model}`
- **THEN** boot raises `PluginError` naming the plugin, the module and the key

#### Scenario: Two plugins claim one seam
- **WHEN** two enabled plugins both declare `workspace.access`
- **THEN** boot raises `PluginError` naming both plugins before the workspace is constructed

#### Scenario: Oscillator seam with the layer off
- **WHEN** a plugin declares `oscillator.sequence` and `[oscillator].enabled` is false
- **THEN** boot raises `PluginError` naming the plugin and the seam

#### Scenario: Declared seam is honoured
- **WHEN** an enabled plugin returns `{"network": model}` for the sequence module and the sequence module is enabled
- **THEN** the constructed sequence module uses `model` as its network and builds no default CfC network

## ADDED Requirements

### Requirement: Workspace seams are filled through the workspace construction path
A plugin that declares a `workspace.*` seam SHALL supply its object through `workspace_injections(config)`, called once when the workspace is built. The object SHALL implement the seam's protocol; a missing method, a `None` value or an exception SHALL raise `PluginError` naming the plugin and the seam. The cycle and every runner that builds a workspace SHALL use this one path.

#### Scenario: A rival access rule is used
- **WHEN** an enabled plugin declares `workspace.access` and returns an object implementing `AccessRule`
- **THEN** the built workspace calls that object's `decide` on every broadcast tick and builds no default access rule

#### Scenario: A runner uses the same path
- **WHEN** the workspace-mediation runner is configured with the same plugin
- **THEN** its workspace uses the plugin's access rule, as a live boot does

#### Scenario: An incomplete object is refused
- **WHEN** a plugin returns for `workspace.context` an object without `null`
- **THEN** boot raises `PluginError` naming the plugin and `workspace.context`

### Requirement: The workspace account is recorded
Every run manifest SHALL carry `workspace_account`, the ids of the salience, access and context implementations in use, with `"default"` for each in-tree default. Every broadcast's metadata SHALL carry the same three ids.

#### Scenario: A default run names the default account
- **WHEN** a run boots with no plugin
- **THEN** its manifest records `workspace_account` with `"default"` for salience, access and context

#### Scenario: A plugin run names its account
- **WHEN** a run boots with a plugin filling `workspace.context` with an encoder whose id is `"ctx-x"`
- **THEN** the manifest and every broadcast record `"ctx-x"` as the context implementation

### Requirement: Research mode refuses an undeclared workspace account
In research mode the research gate SHALL stop the boot when any `workspace.*` seam is filled and the study file does not declare `[study].workspace_account` naming the same plugin and the same seams.

#### Scenario: An installed plugin cannot enter a planned study
- **WHEN** a study whose file declares no workspace account boots in research mode with a plugin filling `workspace.access`
- **THEN** the research gate stops the boot with an error naming the plugin and the seam

#### Scenario: A comparison study declares its account
- **WHEN** a study file declares `[study].workspace_account = { plugin = "rival", seams = ["workspace.access"] }` and that plugin fills exactly that seam
- **THEN** the research gate passes this check
