# Design

## Context

The workspace-feedback extension (PR #516, all tasks complete) gives each processor a top-down head that predicts the next input from the workspace's access summary (a 24-dim context vector of intensity shares). The TopDownBlend routes the head's prediction alongside the processor's own forward-model prediction, blended by precision. Gains move to track which processors are most precise.

This is the prediction-error channel with no content: the access summary says *who* was accessed and *how strongly*, not *what* was perceived. The CTO decided (2026-10-31) to extend this into a content-bearing second level, trained by the same prediction errors.

The existing processors publish latents at each step:
- **Vision**: `latent_dim` from the image encoder (dynamic; 64 for the shipped CfC encoder, up to 384 for DINOv2).
- **Audition**: 9 features (emotion categories + timing/energy).
- **Interoception**: 8 features (drive levels).

These latents are already available via the feedback channel; the content level adds the cross-modal encoding layer.

## Goals / Non-Goals

**Goals:**
- A shared content code `z_k` that represents what was perceived across modalities, updated on every accessed broadcast.
- Per-processor descending predictions that feed back into each processor's forward model through the existing TopDownBlend.
- Training from the processors' own prediction errors, requiring no new loss signal.
- A translation-loss arm for language (the unpaired modality) and as a comparison condition.
- Off by default, bit-identical to absent. Weights under entity identity rules.

**Non-Goals:**
- Changing the workspace's competitive selection mechanism. Selection decides *which* members write into z_k; it is not influenced by z_k.
- Adding a second Redis instance or bus. The shared code rides the existing broadcast metadata.
- Working memory, episodic content grounding, or any downstream consumer of z_k. Those are W2–W5 in the architecture program.
- Pretrained cross-modal encoders (CLIP, SigLIP, ImageBind).
- Language as a content source (language is the translation-loss route, not a prediction-error route, because it arrives unpaired).

## Decisions

### D1. Architecture: encoder → z_k → decoder, one per processor

Each of the three processors (vision, audition, interoception) gets:
- An **encoder** `E_p: R^{d_p} → R^{code_dim}` that maps the processor's latent vector to the shared code space.
- A **decoder** `D_p: R^{code_dim} → R^{d_p}` that maps the shared code back to the processor's latent dimensions.

Both are single-layer linear maps with optional nonlinearity (tanh by default), matching the TopDownHead's complexity. A linear map suffices because the processors' forward models are themselves CfC networks that already produce informative latent representations; a deep encoder/decoder would add parameters without adding information the forward models haven't already extracted.

**Alternative rejected:** convolutional or attention-based encoders. These require batched inputs and are designed for raw observations, not the low-dimensional latent vectors the processors publish.

### D2. Shared code update rule

On each accessed broadcast, z_k is updated as:

    z_k = Σ_p (intensity_p × E_p(latent_p)) / Σ_p intensity_p

where the sum is over accessed processors only, and `intensity_p` is the processor's access intensity from the workspace's selection.

This is a weighted centroid in code space — the processor with the strongest access contribution has the most influence on what the broadcast "contains". When only one processor is accessed (common early in development), z_k is simply that processor's encoded latent.

**Alternative considered:** exponential moving average of z_k across broadcasts (momentum). Rejected because the access summary already captures temporal context; stale z_k would blur the content of distinct broadcasts and make the prediction targets ambiguous.

### D3. Descending prediction through TopDownBlend

The existing TopDownBlend wraps each processor's forward model and optionally blends in a top-down prediction from the workspace-feedback head. The content level adds a second top-down signal:

1. The **content decoder** `D_p(z_k)` produces a prediction in the processor's latent space.
2. This prediction is blended with the feedback head's prediction and the processor's own forward-model prediction, all weighted by precision (inverse recent error).

The TopDownBlend's `hindsight_step` already computes precision weights for the head vs. forward model. Adding the content decoder is a third input to the same blend. The weights become: `w_own`, `w_head`, `w_content`, normalized to sum to 1, each proportional to inverse windowed error.

**Alternative rejected:** separate blend for content (a second TopDownBlend wrapping the first). This doubles the blend machinery for no benefit and makes the precision competition less informative by hiding the content signal behind an intermediate blend.

### D4. Training signal: prediction-error reconstruction

Each processor already computes a forward-model prediction error at every step (the `error_ratio` and `disagreement` reported through the feedback channel). The content level piggybacks on the same signal:

    L_content_p = || D_p(z_k) - observed_latent_p ||^2

where `observed_latent_p` is the latent the processor computed from the actual input at this step, and `z_k` was computed from the *previous* broadcast's accessed latents.

The encoder E_p is trained by backpropagation through D_p's loss: the gradient flows through D_p(E_p(latent_p)), which is a standard autoencoder reconstruction path. The cross-modal signal comes because z_k mixes *all* accessed processors' encodings, so D_p(z_k) for processor p is influenced by processors q ≠ p.

This is a pure numpy implementation, not a torch autograd graph. The TopDownHead already uses manual gradient updates (adapt method); the content encoder/decoder follows the same pattern.

### D5. Translation-loss arm (cycle-consistency for language)

When `arm = "translation"`, the training signal changes to cycle-consistency:

    For each pair of accessed processors (p, q):
        L_cycle = || D_p(E_q(latent_q)) - latent_p ||^2 + || D_q(E_p(latent_p)) - latent_q ||^2

This is VanRullen & Kanai's (2021) cross-modal translation objective. It trains the encoders to produce a code from which any processor's latent can be reconstructed, even without paired supervision from the target modality.

The translation arm is primarily the route for **language**: the language module's output (text tokens, intent) is unpaired with the sensory modalities — there is no frame-aligned audio-text or video-text ground truth in the entity's own experience. Cycle-consistency solves exactly this: it trains cross-modal reconstruction without requiring paired data.

The prediction-error arm remains the default and the one used for the three sensory processors. The translation arm is a second condition for the study, selectable per run.

### D6. Timing: content update runs inside the broadcast tick

The content level runs in the existing broadcast tick:

1. **Selection** produces the coalition (unchanged).
2. **Content update**: for each accessed processor, encode its latent; combine into z_k.
3. **Feedback**: the feedback controller runs as before, but now the TopDownBlend for each processor also receives D_p(z_k) as a third prediction input.
4. **Training**: after the processor's forward model observes the actual input, the content encoder/decoder pair updates from the reconstruction error.

Steps 2 and 3 add computation proportional to `code_dim × max(d_p)` per tick, which is negligible (the forward models are already the bottleneck).

### D7. Configuration

```toml
[workspace.content]
enabled = false       # off by default
arm = "prediction"    # "prediction" or "translation"
code_dim = 32         # shared code dimension
encoder_lr = 1e-3     # encoder learning rate
decoder_lr = 1e-3     # decoder learning rate
```

`code_dim = 32` is a conservative starting point. The three processor latent dimensions are 64/9/8; 32 is larger than the smallest (interoception, 8) and smaller than the largest (vision, 64), forcing compression of the vision latent while leaving room for the audition and interoception signals.

### D8. Implementation files

- `kaine/workspace/content.py` (new): `ContentLevel` class holding the encoders, decoders, z_k, update and training logic.
- `kaine/workspace/feedback.py`: `FeedbackController` extended with a `content` attribute; the broadcast metadata gains a `"content"` key when the level is active.
- `kaine/modules/feedback.py`: `TopDownBlend.hindsight_step` accepts an optional `content_prediction` argument; `blend_weights` becomes a 3-way blend when content is present.
- `kaine/lifecycle/preservation.py`: `preserve_live` and `revive` handle `workspace_content` metadata.
- `kaine/cycle/__main__.py`: `_phase_workspace` wires the content level; the broadcast tick calls content update and training.
- `config/kaine.toml`: the `[workspace.content]` section.

## Risks / Trade-offs

### R1. Code dimension too small
If `code_dim` is too small, the shared code cannot represent all three modalities faithfully. The decoder reconstruction error will be high for the most complex modality (vision). Mitigation: `code_dim` is configurable; the reconstruction error per processor is logged; the first development run will show whether 32 suffices or needs raising.

### R2. Vision dominates the code
Vision's latent dimension (64) is much larger than audition (9) or interoception (8). Even with intensity weighting, vision may dominate z_k simply because it has more variance to encode. Mitigation: the encoders are independent; each maps its own latent space to code_dim. The intensity weighting in the combination step normalizes across processors. If vision still dominates, a per-processor normalization of encoded values (unit-variance in code space) can be added without changing the architecture.

### R3. Training instability early in development
Early in the entity's development, the forward models are still learning and their latents are noisy. The content encoder/decoder will train on noisy targets. Mitigation: the content level starts from random weights and learns alongside the forward models, so both improve together. The off-by-default configuration means the content level joins after the forward models have stabilized (the operator enables it when ready, or it enables automatically at a maturation stage).

### R4. Backward compatibility
Snapshots taken before the content level was built will not contain `workspace_content` metadata. Revive must handle this gracefully by starting the content level fresh. The preservation code already handles this pattern (workspace-feedback uses the same pending-state mechanism).

### R5. Privacy of the shared code
z_k is a learned latent vector trained from the entity's own perceptual experience. The privacy rule for latent-derived content (PR #656) already establishes that latent-derived content is never logged as text, never stored as an episode, and stripped by the privacy filter. z_k falls under this rule. The research log records presence and dimension, not values.
