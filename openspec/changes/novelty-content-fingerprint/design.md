## Context

`fingerprint()` and `NoveltyTracker` are unchanged since the initial release. The salience product is `intensity × novelty × goal × thymos` (`2026-07-10-wire-salience-goal-thymos`).

## Decisions

### D1. Measure before choosing

The quantisation resolution decides how similar two perceptual reports must be to count as "the same content". Choosing it blind would hard-wire a perceptual threshold, so Phase 1 measures the real payloads first.
- **Measured:** the per-field value ranges and step-to-step changes, and the novelty distribution per source under candidate resolutions.
- **The choice:** the coarsest resolution that still separates the seeded feed's marked scene changes from steady state.

### D2. Vectors never enter the fingerprint

Vectors are removed with the same rule the diagnostics surface and Mnemos use (`strip_vectors`). A latent is a perceptual encoding, not content identity. Its change already reaches salience through the module's own prediction error, so counting it again in novelty would double-count the same signal.

### D3. Purity

The fingerprint stays a pure function of the event, so salience stays a pure function of its inputs and the deterministic cycle mode is unaffected.

## Risks

- **Over-quantising** would make distinct scenes look identical and suppress real novelty. The record states each source's habituation profile under the chosen rule, and the tests pin that a marked scene change still scores 1.0.
