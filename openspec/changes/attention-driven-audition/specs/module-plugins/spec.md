## MODIFIED Requirements

### Requirement: Plugins fill only declared seams
A plugin SHALL declare its seams when it is loaded, and SHALL be able to fill only seams KAINE declares: `sequence.network`, `interoception.forward_model`, `planning.engine`, `audition.acoustic_encoder`, and `oscillator.<module>`. A plugin declaring an unknown seam, two plugins declaring the same seam, or a plugin returning a seam it did not declare SHALL cause boot to raise `PluginError`. Seam validation and conflict detection SHALL happen before any module is constructed. A plugin SHALL NOT be able to enable or disable modules, switch on the oscillator layer, or change configuration.

#### Scenario: Unknown seam
- **WHEN** a plugin declares `sequence.cfc_units`
- **THEN** boot raises `PluginError` naming the plugin and the seam before any module is constructed

#### Scenario: Returned seam was not declared
- **WHEN** a plugin declared only `sequence.network` and its `injections` for the interoception module returns `{"forward_model": model}`
- **THEN** boot raises `PluginError` naming the plugin, the module and the key

#### Scenario: Two plugins claim one seam
- **WHEN** two enabled plugins both declare `sequence.network`
- **THEN** boot raises `PluginError` naming both plugins before any module is constructed

#### Scenario: Oscillator seam with the layer off
- **WHEN** a plugin declares `oscillator.sequence` and `[oscillator].enabled` is false
- **THEN** boot raises `PluginError` naming the plugin and the seam

#### Scenario: Declared seam is honoured
- **WHEN** an enabled plugin returns `{"network": model}` for the sequence module and the sequence module is enabled
- **THEN** the constructed sequence module uses `model` as its network and builds no default CfC network

#### Scenario: Audition encoder seam is honoured
- **WHEN** an enabled plugin declares `audition.acoustic_encoder` and returns `{"acoustic_encoder": encoder}` for Audition
- **THEN** the constructed Audition uses `encoder` for general acoustic perception
