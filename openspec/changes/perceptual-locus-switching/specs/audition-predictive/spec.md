## ADDED Requirements

### Requirement: Auditory forward-model contexts are kept per source
With the perceptual-source registry on, the audition processor SHALL keep one context per source id, holding its forward model and its acoustic forward models with their windows and baselines. It SHALL bind contexts on each source epoch, start a never-seen source from copied weights with empty buffers and windows, and serialise the bank under `forward_model_bank` in the audition weight group.

#### Scenario: A source without sound
- **WHEN** the entity is in a source that declares no audio
- **THEN** the audition bank is unchanged, and no context is created for that source
