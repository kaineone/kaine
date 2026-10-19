## ADDED Requirements

### Requirement: The null context differs from the held context only where other sources contributed
When the vision, audition or interoception module forms a prediction, it SHALL build its broadcast context and the null context of the information-gain measure from one reading of the clock. The null context SHALL equal the held context in the age and the two flags; in every component that sums per-event contributions it SHALL hold the kept sources' current share plus the mean, over the contexts the processor has adopted so far, of the other sources' share; and in the coalition-level components it SHALL hold their means over the same contexts. When every adopted context is the same, the null context SHALL equal the held context and the reported gain SHALL be zero.

#### Scenario: Only other sources' contributions are replaced
- **WHEN** a processor has adopted three broadcasts whose members come from several sources and builds its context and null context on a clock that advances on every reading
- **THEN** the null context's additive components equal the kept sources' current share plus the mean of the other sources' share, its components 0 to 3 equal their means over the three contexts, and its components 20 to 22 equal the held context's

#### Scenario: A context that carries nothing gives zero gain
- **WHEN** the vision or interoception module adopts broadcasts of identical content before each report
- **THEN** each report's `context_gain` is exactly 0 and its `null_prediction_error` equals its `prediction_error`

### Requirement: Reports carry the paired evaluations behind the gain
Each report of the vision module, audition's acoustic path and the interoception module that carries a `context_gain` SHALL also carry `null_prediction_error`, the error of the prediction formed with the null context, and `mean_prediction_error`, the running mean error the gain is divided by, so that `context_gain` equals their difference from `prediction_error` over the mean. When `context_gain` is null both SHALL be null. A reading the interoception module skips as non-finite SHALL report no gain and SHALL NOT enter the running mean, and it SHALL leave no prediction behind, so the next reading also reports no gain and makes no update.

#### Scenario: The gain is recoverable from the paired evaluations
- **WHEN** the vision module reports after adopting two different broadcasts
- **THEN** `context_gain` equals `(null_prediction_error - prediction_error) / mean_prediction_error`

#### Scenario: A skipped reading reports no gain
- **WHEN** the interoception module's forward model receives a non-finite feature vector after scoring a prediction formed with a context
- **THEN** it returns an error of 0 and holds no null error, so no gain is published for that reading, the running mean error is unchanged, and the next reading publishes no gain either
