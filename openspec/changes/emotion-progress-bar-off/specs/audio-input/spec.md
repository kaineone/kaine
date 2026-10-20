## ADDED Requirements

### Requirement: The emotion classifier keeps funasr progress bars out of the log
`Emotion2vecClassifier` SHALL construct its funasr `AutoModel` with `disable_pbar=True`, so classification writes no tqdm progress bar to stderr. The setting SHALL NOT change the classifier's inputs or results.

#### Scenario: The model is built with progress bars off
- **WHEN** the classifier loads its funasr model for the first classification
- **THEN** the `AutoModel` constructor receives `disable_pbar=True` together with `disable_update=True`, the model id, the device and the hub

#### Scenario: Results are unchanged
- **WHEN** the funasr model returns the label `happy` with score 0.9
- **THEN** the classifier returns category `happy` with confidence 0.9, as before the change
