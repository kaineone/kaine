## ADDED Requirements

### Requirement: The diagnostics privacy filter removes numeric vectors
The diagnostics privacy filter SHALL remove, at every nesting depth, every field named in its vector-field set (`latent`, `peripheral`, `foveal`, `temporal_context`, `feature_vector`) and every list or tuple of 16 or more numbers (booleans excluded) whose key is not a reviewed non-embedding key (`saliences`, `step_magnitudes`). No perceptual or latent embedding SHALL reach the Nexus stream, the Nexus record or any other surface that uses the filter.

#### Scenario: A vision report
- **WHEN** a `topos.report` carrying `latent`, `peripheral` and `foveal` passes the filter
- **THEN** all three are removed and its scalar fields, `fovea` and `predicted_fovea` are kept

#### Scenario: A short test latent
- **WHEN** a payload carries `latent` with four numbers
- **THEN** it is removed

#### Scenario: An unnamed embedding
- **WHEN** a payload carries a field `embedding_x` holding 64 numbers
- **THEN** it is removed

#### Scenario: Small and reviewed lists survive
- **WHEN** a payload carries `scores` with 5 numbers and `saliences` with 40 numbers
- **THEN** both are kept
