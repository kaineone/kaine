## MODIFIED Requirements

### Requirement: TrainingResult populates voice-tracking fields
The returned `TrainingResult` SHALL include the fields the evaluation sidecar's `voice_tracking.py` consumes from the published sleep event: `pairs_processed`, `pairs_above_threshold`, `dpo_loss`, `adapter_accepted`, `capability_score_before` and `capability_score_after`. `mean_intent_expression_similarity_before` and `mean_intent_expression_similarity_after` SHALL be null on every trainer backend, because the shared trainer script cannot compute them without importing `kaine`. Every consumer SHALL treat a null similarity as absent, never as zero.

#### Scenario: Sidecar sees real numbers
- **WHEN** a real training pass completes and the sleep event is published
- **THEN** the evaluation sidecar's `voice_tracking-<date>.jsonl` contains an entry with a non-None `dpo_loss`, and `mean_similarity_before` and `mean_similarity_after` are null
