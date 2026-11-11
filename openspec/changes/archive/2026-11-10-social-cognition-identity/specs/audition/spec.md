# Spec Delta

## ADDED Requirements

### Requirement: Speaker embedding extraction publishes audition.speaker_embedding events
The audition module SHALL run a config-gated speaker embedding extractor alongside the existing STT and emotion pipelines. When enabled, it SHALL extract a speaker embedding from each processed audio window and SHALL publish an `audition.speaker_embedding` event carrying the embedding vector, source label, and confidence.

#### Scenario: Speaker embedding published on processed audio
- **WHEN** the speaker embedding extractor is enabled and the audition module processes an audio window
- **THEN** the module SHALL publish an `audition.speaker_embedding` event with a 192-dimensional embedding vector, the source label, and a confidence score

#### Scenario: Speaker embedding disabled by default
- **WHEN** the system boots with shipped default configuration
- **THEN** no speaker embedding extractor SHALL be loaded and no `audition.speaker_embedding` events SHALL be published

#### Scenario: Speaker embedding independent of STT
- **WHEN** the speaker embedding extractor is enabled
- **THEN** it SHALL operate independently of the STT pipeline. A failure or absence of the STT model SHALL NOT prevent speaker embedding extraction, and vice versa

### Requirement: audition.speaker_embedding event payload
Each `audition.speaker_embedding` event SHALL carry `embedding` (list of 192 floats), `source_label` (string), and `confidence` (float in [0, 1]). The event SHALL carry `degraded: true` when the speaker embedding model is unavailable or produces a non-finite embedding.

#### Scenario: Degraded embedding when model absent
- **WHEN** the speaker embedding model is configured but fails to load
- **THEN** the audition module SHALL publish `audition.speaker_embedding` with `degraded: true` and a null embedding, so downstream consumers can gate on the flag
