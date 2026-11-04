# Proposal

## Why

The workspace broadcasts accessed reports whole, but processors only read an **access summary**: which modules won access and how strongly. Nothing represents or remembers what was perceived across senses. This blocks working memory, episodic content, world-model grounding, and cross-modal learning.

The CTO decided (2026-10-31) that the workspace will carry content. The approved direction is **option F**: a content-bearing second level trained by the processors' own prediction errors, descending predictions through the existing workspace-feedback head. The workspace-feedback extension (PR #516, completed) is the foundation this builds on.

## What Changes

A **content level** joins the existing workspace as a held extension of workspace-feedback:

1. **Per-source content encoders** map each processor's published latents into a shared code `z_k`, updated on accessed broadcasts only, intensity-weighted.

2. **Per-processor content decoders** produce a descending prediction of each processor's next input, blended by precision through the existing `TopDownBlend` (the workspace-feedback head).

3. **Training** uses the processors' own prediction errors: each processor already computes this for its forward model, and the content encoder/decoder pair learns from the same signal.

4. The existing access summary is extended with the shared code `z_k`, available to any module that reads the broadcast.

5. A **translation-loss arm** (VanRullen & Kanai 2021 cycle-consistency) is kept only as a comparison arm and as the route for language, the one truly unpaired modality.

6. **Off by default**, bit-identical to absent when off. Learned weights under entity identity rules (persist, encrypt, copy into forks). The content level has its own arm in `[workspace.content]`, independent of the feedback arm.

## Capabilities

### New Capabilities
- `workspace-content`: the content-bearing second level of the workspace — per-source encoders, shared code, per-processor decoders, training from processor prediction errors, and the translation-loss comparison arm

### Modified Capabilities
- `workspace-feedback`: the feedback head gains a content-prediction input alongside the existing context+sequence input; the TopDownBlend routes the content decoder's descending prediction to the processor's forward model
- `preservation`: the content encoder/decoder weights and the shared code are preserved and revived with the entity

## Impact

- `kaine/workspace/content.py` (new): content encoders, decoders, shared code, training loop
- `kaine/workspace/feedback.py`: TopDownBlend extended to accept content decoder output; FeedbackController extended with content level orchestration
- `kaine/modules/feedback.py`: TopDownHead and TopDownBlend accept an optional content prediction input alongside the existing sequence prediction
- `kaine/lifecycle/preservation.py`: preserve and revive content encoder/decoder weights
- `kaine/cycle/__main__.py`: wire the content level into the broadcast cycle
- `kaine/boot/wiring.py`: content level construction and module registration
- `config/kaine.toml`: `[workspace.content]` section with `enabled`, `arm`, `code_dim`, `encoder_lr`, `decoder_lr`
- Tests: content round-trip, off-equals-absent identity, preservation, integration with each processor
