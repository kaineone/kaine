# Tasks

## 1. Content level core

- [ ] 1.1 `kaine/workspace/content.py`: `ContentLevel` class with per-source `ContentEncoder` (linear d_p → code_dim, tanh), per-processor `ContentDecoder` (linear code_dim → d_p, tanh), shared code `z_k` update (intensity-weighted centroid), and reconstruction-error training step. Pure numpy, matching TopDownHead's style.
- [ ] 1.2 `ContentLevel.state_dict()` / `load_state_dict()` for preservation: encoder weights, decoder weights, current `z_k`. Finite-weights guard on load, shape-mismatch rejection, backward compat (missing keys → fresh init).
- [ ] 1.3 Tests: `tests/test_content_level.py` — encoder/decoder round-trip, z_k update with intensity weighting, training step reduces reconstruction error over 50 steps, state_dict round-trip, shape mismatch rejection, off-by-default produces no side effects.

## 2. Translation-loss arm

- [ ] 2.1 Cycle-consistency training in `ContentLevel`: for each pair of accessed processors, compute round-trip reconstruction loss and update encoder/decoder weights. Selectable via `arm = "translation"`.
- [ ] 2.2 Tests: `tests/test_content_translation_arm.py` — cycle loss decreases over steps for two synthetic processors, the prediction arm and translation arm produce different weight trajectories on the same data.

## 3. TopDownBlend integration

- [ ] 3.1 `TopDownBlend.hindsight_step` accepts an optional `content_prediction` argument; `blend_weights` becomes a 3-way blend (own, head, content) when content is present, with precision weights from windowed errors.
- [ ] 3.2 Tests: `tests/test_feedback_content_blend.py` — 3-way blend with known precisions matches expected weights; content_prediction=None falls back to 2-way blend; state_dict/load_state_dict includes content error window.

## 4. FeedbackController and broadcast wiring

- [ ] 4.1 `FeedbackController` holds an optional `ContentLevel`; on each accessed broadcast, the controller updates z_k and attaches `metadata["content"]` to the broadcast snapshot.
- [ ] 4.2 `_phase_workspace` in `kaine/cycle/__main__.py`: construct `ContentLevel` from `[workspace.content]` config; wire into the feedback controller. Handle `pending_content_state` from revive.
- [ ] 4.3 Preservation: `preserve_live` captures `workspace_content` metadata; `revive` stores it as `pending_content_state`. Matches the workspace-feedback pattern.
- [ ] 4.4 Tests: `tests/test_content_broadcast.py` — broadcast carries content when enabled, no content key when disabled; selection produces the same coalition with and without content (identity check).

## 5. Processor integration

- [ ] 5.1 Vision: the content decoder's prediction feeds into vision's TopDownBlend; training uses vision's latent as the reconstruction target.
- [ ] 5.2 Audition: same integration for the audition processor.
- [ ] 5.3 Interoception: same integration for the interoception processor.
- [ ] 5.4 Tests: `tests/test_content_processor_integration.py` — each processor's TopDownBlend receives the content prediction and blends correctly; content-off matches content-absent.

## 6. Configuration and docs

- [ ] 6.1 `config/kaine.toml`: `[workspace.content]` section with defaults (`enabled = false`, `arm = "prediction"`, `code_dim = 32`, `encoder_lr = 1e-3`, `decoder_lr = 1e-3`).
- [ ] 6.2 Docs: workspace chapter update (content level, shared code, descending predictions), configuration appendix.
- [ ] 6.3 Research-log integration: log content presence, code dimension, per-processor reconstruction error.

## 7. Review

- [ ] 7.1 Worker first-pass review.
- [ ] 7.2 Independent second review (welfare: learned weights, privacy boundary, identity rules).
