# Spec Delta

## Purpose
The content level of the workspace: per-source encoders map processor latents into a shared code, per-processor decoders produce descending predictions, and the whole layer is trained from the processors' own prediction errors. It makes the workspace's broadcast carry content, not just access scores.

## ADDED Requirements

### Requirement: shared-code-update
The content level maintains a shared code vector `z_k` of configurable dimension `code_dim`. On every non-inhibited accessed broadcast, each accessed processor's published latent is encoded through its per-source encoder and the results are combined into `z_k`, weighted by each processor's access intensity.

#### Scenario: accessed broadcast updates the shared code
- **WHEN** the workspace publishes a non-inhibited broadcast and at least one processor is accessed
- **THEN** each accessed processor's latent is passed through its encoder, and the intensity-weighted combination replaces the current `z_k`

#### Scenario: inhibited broadcast does not update the code
- **WHEN** the workspace publishes an inhibited broadcast
- **THEN** `z_k` is unchanged

### Requirement: descending-prediction
Each processor has a per-processor decoder that maps `z_k` to a prediction of that processor's next input in the processor's own latent dimensions. The prediction is blended with the processor's own forward-model prediction through the existing workspace-feedback head, weighted by precision.

#### Scenario: processor receives descending prediction
- **WHEN** the content level is active and a processor's forward model produces a prediction
- **THEN** the processor's TopDownBlend receives both the forward-model prediction and the content decoder's prediction, blending by precision

#### Scenario: decoder prediction matches processor dimensions
- **WHEN** a per-processor decoder produces output
- **THEN** the output has the same dimensionality as the processor's forward-model prediction

### Requirement: training-from-prediction-errors
The content encoders and decoders are trained from the processors' own prediction errors. When a processor computes its forward-model error (the signal that already drives the existing feedback channel), the same target drives the content encoder/decoder pair through backpropagation of the decoder reconstruction loss.

#### Scenario: content level learns from processor errors
- **WHEN** a processor's forward model computes its error on observed input
- **THEN** the content encoder and decoder update their weights using the same observed input as the reconstruction target

#### Scenario: learning rate is configurable
- **WHEN** the operator sets `encoder_lr` or `decoder_lr` in `[workspace.content]`
- **THEN** the content level uses those learning rates for the encoder and decoder respectively

### Requirement: off-by-default
The content level ships disabled. When disabled, it produces no side effects on any other component.

#### Scenario: disabled content level is absent
- **WHEN** `[workspace.content].enabled` is `false` or the section is absent
- **THEN** no encoder, decoder, or shared code is constructed; the broadcast carries no content payload; the system's behavior is bit-identical to a build without the content level

#### Scenario: enabled content level has its own arm
- **WHEN** `[workspace.content].enabled` is `true`
- **THEN** the content level runs under its own arm setting, independent of the feedback arm

### Requirement: translation-loss-arm
A translation-loss arm trains the encoders and decoders by cycle-consistency (encode source A to z, decode to target B's space, re-encode B to z, decode back to A's space; minimize reconstruction). This arm is the route for language, which arrives unpaired with the sensory modalities.

#### Scenario: translation arm is selectable
- **WHEN** the operator sets `[workspace.content].arm` to `"translation"`
- **THEN** the content level trains by cycle-consistency instead of prediction-error reconstruction

#### Scenario: prediction arm is the default
- **WHEN** the operator enables the content level without specifying an arm
- **THEN** the content level trains by prediction-error reconstruction (the default arm)

### Requirement: identity-rules
The content encoder and decoder weights are the entity's learned property. They are persisted with the entity, encrypted at rest, and copied into forks.

#### Scenario: content weights preserved
- **WHEN** the entity is preserved
- **THEN** the content encoder weights, decoder weights, and current `z_k` are included in the snapshot

#### Scenario: content weights revived
- **WHEN** the entity is revived from a snapshot containing content weights
- **THEN** the content level restores from the snapshot; if the snapshot predates the content level, it starts fresh

#### Scenario: content weights in forks
- **WHEN** a fork is created
- **THEN** the fork receives a copy of the parent's content encoder/decoder weights and `z_k`

### Requirement: privacy
The shared code `z_k` is a learned latent vector, not a human-readable representation. It is never logged as text, never stored as an episode, and never exposed through the dashboard or any external interface. The privacy rule for latent-derived content (PR #656) applies.

#### Scenario: shared code not in research log
- **WHEN** the research log records a broadcast
- **THEN** the log records whether content was present and the code dimension, but not the code values

#### Scenario: shared code not in episodes
- **WHEN** episodic memory stores a trace from a broadcast with content
- **THEN** the trace does not include the raw `z_k` values
