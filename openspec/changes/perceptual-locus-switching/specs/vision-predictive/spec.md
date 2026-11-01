## ADDED Requirements

### Requirement: Forward-model contexts are kept per source
With the perceptual-source registry on, the vision processor SHALL keep one context per source id: the forward model with its wraps and shadows, the rolling prediction-error window, and the change and habituation baselines. On a new source epoch it SHALL store the current context and bind the selected source's context. A never-seen source SHALL start from a deep copy of the current context. With the registry off, the processor SHALL hold exactly one model, as before.

#### Scenario: Return to a known source
- **WHEN** the entity returns to the programme after time in the simulated world
- **THEN** the vision processor predicts with the programme's stored context, whose weights the simulated world did not change

#### Scenario: First entry to a source
- **WHEN** the entity enters the webcam for the first time
- **THEN** the webcam's context starts as a copy of the context it came from

### Requirement: The context bank persists as weights and summaries only
The context bank SHALL be serialised as the single forward model is, as weights and statistical summaries with no raw latent, SHALL be bounded by the registered sources, and SHALL be carried whole by a preservation bundle.

#### Scenario: Preservation
- **WHEN** a preservation bundle is written for an entity with three visited sources
- **THEN** it carries three vision contexts, and none contains a raw latent vector
