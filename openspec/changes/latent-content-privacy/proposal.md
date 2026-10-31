## Why

On 2026-10-31 the operator decided that KAINE's workspace will carry content, built as option F of the global-latent-workspace comparison: a code `z_k` learned from the processors' perceptual latents and sent back down as predictions (change `workspace-content-code`). Content-bearing memory, grounding and working memory follow it. Every one of these components holds values computed from perceptual latents. The comparison report's finding F10 names the problem: the current privacy rules were written for a system with no such values, so a content code's logging and persistence policy would be inherited by accident unless it is designed first. The operator's decision fixes the principle: latent-derived content may live in working state and in learned weights; it is never logged, never stored as an episode, and it is stripped by the privacy filter. This change turns that principle into a rule the code can enforce, and it is the prerequisite for every content-bearing component (build order item 2).

The existing rules do not cover latent-derived values:

- **The vector rule is by name and length.** The privacy filter removes the named vector fields (`latent`, `peripheral`, `foveal`, `temporal_context`, `feature_vector`) and any unnamed numeric list of 16 or more numbers (`kaine/privacy_filter.py`, `VECTOR_BACKSTOP_MIN_LEN`). A content code of 8 numbers, an interoceptive prediction decoded from a code (8 numbers), or any projection published under a new key passes it.
- **Not every persisting surface uses the filter.** The curated research log, the dashboard stream and its record use it. The raw bus archive writes verbatim events once both attestations are set (spec `research-event-log`). Fork snapshots and preservation bundles hold whatever each module's `serialize()` returns, and nothing checks it. Python log messages are not checked at all.
- **Snapshots already persist latent statistics.** `VisionForwardModel.buffer_summary()` writes the per-feature mean and variance of the last 16 clip latents into every snapshot and preservation bundle (`kaine/modules/vision/forward.py:503`, `kaine/modules/vision/module.py:996`). The acoustic forward model does the same for acoustic embeddings (`kaine/modules/audition/module.py:1135`). Sixteen clips are about five seconds of one shot, so the mean is close to a single clip embedding of the last thing the entity saw, and clip embeddings can be partly inverted to images (archived change `2026-10-03-workspace-graph-only-recording`). Nothing reads these summaries back on restore. The requirement that asked for them (specs `vision-predictive` and `audition-predictive`, "Buffer summary ... statistical descriptor") predates the content decision and treats a per-dimension mean as harmless.
- **Episodic memory's omit list is narrower than the language module's heard rule.** The store drops the payloads of `audition.transcription` and `embodiment.visual.raw` only (`kaine/modules/episodic_memory/module.py:573-578`). The language module's heard rule also covers `embodiment.chat` and heard-text fields at any depth (`kaine/modules/language/context.py:271-302`). The design-only change `episodic-recall-content` fixes this in its first PR. It was scheduled after the module-ignition study, which no longer exists as a gate: the study converts into the development run, and the episodic memory module joins that run early.

## What Changes

- **One latent rule, by provenance.** A value is latent-derived when it is computed from a perceptual latent, or from another latent-derived value, and keeps per-dimension information: codes, projections, decoder outputs and predictions in a latent space, residual and gradient vectors, and per-dimension statistics over any window. Scalar reductions (norms, distances, mean squared errors, ratios, information gains, counts) are not latent-derived. Learned parameters are not values under this rule; they are identity and follow the identity rules.
- **One tag.** Latent-derived values travel only inside a mapping under the reserved key `latent_derived`, at any depth. Perceptual latents keep their existing names. `kaine/privacy_filter.py` gains `LATENT_FIELDS` (the vector fields plus `latent_derived`) and `strip_latent()`, which removes those keys at any depth regardless of length. `latent_derived` joins the vector fields, so the diagnostics filter and the episodic store's `strip_vectors` remove it too.
- **The strip points.**
  - Every JSONL sink (`kaine/persistence/jsonl_sink.py`, used by the research log, the ignition log, the incident log, the dashboard record, the raw archive and every observer) applies `strip_latent()` to each record before it is encoded.
  - The raw bus archive stays verbatim except for the latent fields.
  - The workspace broadcast record removes each selected member's `latent_derived` mapping, so an ascending error published by a processor never rides the broadcast as well.
  - Fork snapshots and preservation bundles: a module state holds no latent-set value except learned parameters that the module reads back on restore. A snapshot that holds one has it stripped, the module named in the snapshot metadata and an error logged. A preservation is never refused for it.
  - The vision and acoustic buffer summaries become content-free scalars.
  - Episodic memory stores no latent-set value. The heard rule of `episodic-recall-content` PR 1 is applied first, then the raw-perceptual omit, then `strip_latent()`.
  - Python log calls never format a latent-set value.
- **Bounded bus retention.** The bus is working state. A stream that carries `latent_derived` values may have a cap of at most `[privacy].latent_stream_maxlen` entries (default 12000, the `vision.out` cap). The boot refuses when any producer of latent-derived values is enabled and a stream it publishes on exceeds the cap.
- **Offline stimulus features are outside the rule.** Latents computed entity-free from stimulus files by tools scripts (the cross-modal decodability check is one) describe the stimulus, not an entity's experience. They never enter an entity's state tree or the shipped image.
- **Tests.**
  - A persistence canary: an entity-free run with every persisting surface on, in which no latent-set value produced in working state appears in any persisted file, decrypted.
  - A publisher review test: every numeric list a module publishes sits under a latent field or a reviewed non-latent key.
  - Filter, sink, broadcast-record, snapshot, buffer-summary, retention and log-capture tests.

## Capabilities

### New Capabilities

- `latent-content-privacy`: the latent rule, its tag, the strip points, the bus retention bound and the canary test.

### Modified Capabilities

- `research-event-log`: the diagnostics filter removes `latent_derived`; the raw archive is verbatim except for the latent fields.
- `vision-predictive`: the serialized buffer summary holds content-free scalars only.
- `audition-predictive`: the same for the auditory and acoustic buffer summaries.
- `episodic-memory`: stored traces hold no latent-set value, and the order of the store-time rules is fixed.

## Impact

- **Code:** `kaine/privacy_filter.py`, `kaine/persistence/jsonl_sink.py`, `kaine/cycle/engine.py` (`_snapshot_to_payload`), `kaine/lifecycle/snapshot.py` (`save_snapshot`), `kaine/modules/vision/forward.py`, `kaine/modules/audition/forward.py`, `kaine/modules/audition/module.py`, `kaine/modules/episodic_memory/module.py`, `kaine/evaluation/observers/raw_bus_archive_consumer.py` (docstring), `kaine/preboot` (bus budget row), `kaine/bus/config.py` (the retention check), `config/kaine.toml` (`[privacy].latent_stream_maxlen`).
- **Tests:** new `tests/test_latent_content_privacy.py`, `tests/test_latent_persistence_canary.py` and `tests/test_publisher_numeric_keys.py`; updated buffer-summary tests in `tests/test_vision_forward.py`, `tests/test_audition_forward.py`, `tests/test_audition_module.py` and `tests/test_audition_persistence.py`.
- **Behaviour with the shipped configuration:** no event, broadcast or diagnostics payload changes, since nothing publishes `latent_derived` yet. Snapshots and bundles lose the two per-dimension buffer summaries, which nothing reads. Attested raw archives lose the vision latents.
- **Ordering:** before the development run's image is built (build order item 2). `episodic-recall-content` PR 1 (the shared heard rule) is pulled forward to land before or with this change's episodic PR. Every content-bearing component depends on this change: `workspace-content-code` refuses to start without it.
- **Welfare and risk class:** privacy and persistence, so every PR gets the independent second review.
- **Paper:** a REVISION-NOTES entry stating the principle beside "no pixels reach the workspace" (§3.5) and the privacy paragraph of §6.
- **Docs:** the security and privacy chapter, the preservation chapter (what a bundle holds), the configuration appendix.
