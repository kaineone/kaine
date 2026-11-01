## ADDED Requirements

### Requirement: Forward-model contexts are kept per source
With the perceptual-source registry on, the vision processor SHALL keep one context per source id: the forward model's weights, the rolling prediction-error window, and the change and habituation baselines. On a new source epoch it SHALL store the current context and bind the selected source's context. With the registry off, the processor SHALL hold exactly one model, as before.

#### Scenario: Return to a known source
- **WHEN** the entity returns to the programme after time in the simulated world
- **THEN** the vision processor predicts with the programme's stored context, whose weights the simulated world did not change

### Requirement: A first entry copies weights, never buffers
A never-seen source's context SHALL start from a fresh model loaded from the current model's weights, with an empty recurrent buffer, empty windows and baselines, and no alert until its window holds a quarter of `prediction_error_window`.

#### Scenario: First entry from the room
- **WHEN** the entity enters the simulated world for the first time from the webcam
- **THEN** the new context holds the webcam context's weights and no latent of the room

### Requirement: The context bank is a declared weight group
The bank SHALL be serialised under `forward_model_bank`, declared in the vision weight group, so that a merge takes the whole bank from one named parent or refuses. It SHALL hold weights and statistical summaries only, and a preservation bundle and a fork SHALL carry it whole. The weight-group guard test SHALL include a populated bank.

#### Scenario: A merge of two parents with different banks
- **WHEN** two parents with different visited sources are merged and the vision parent is named
- **THEN** the merged entity's bank is that parent's whole bank, and the merge record names the contexts not taken
