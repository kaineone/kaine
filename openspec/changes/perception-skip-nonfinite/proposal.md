## Why

The paper (§5.4, operating details) states that non-finite readings are skipped without updating any model. Soma's forward model already does this: on a non-finite reading it clears its stored prediction, null prediction, context and hidden state, returns an error of 0, and Soma keeps the skipped reading out of its running mean error, so neither that reading nor the next one reports a gain (A.8).

The forward models of Topos and of Audition (the acoustic path and the tone path share one class) do not. On a non-finite embedding they score it against the stored prediction, which gives a non-finite error, and append it to their input buffer. The gradient guard skips the weight update, but every prediction that reads the buffer is non-finite until the reading leaves the buffer, and the non-finite error sits in the module's running error window for as long. While it is there the running mean is undefined, so no report of that module has a gain or a graded intensity above the baseline.

The acoustic change score has the same fault: Audition compares the embedding with the previous one, publishes a non-finite change score, appends it to its change history and keeps the embedding as the next comparison. The change alert then cannot fire until the value leaves the history. Topos's change detector stores the non-finite embedding as its next comparison and records a change of 0 twice, its habituator keeps the embedding in its window, and its report publishes the non-finite latent on the bus.

The positive control's shadows (A.8) already skip a non-finite input and re-seed their hindsight pairing on the next one. The live models have to skip in the same way for the pairing to stay exact.

## What Changes

- On a non-finite input, `LatentForwardModel.step` and `AuditoryForwardModel.step` skip the reading as Soma does: no buffer append and no weight update; the stored prediction, null prediction and context are cleared; the null error is cleared and the reading is marked skipped (`last_reading_skipped`); the error returned is 0. The next reading is scored like a first reading: it returns 0, reports no gain and makes no update, and it re-seeds the prediction.
- Topos and Audition leave a skipped reading out of their running error windows (Topos, Audition's acoustic path and its tone path). The skipped report therefore has a ratio of 0, the baseline intensity and no alert from the forward-model path, and `context_gain`, `null_prediction_error` and `mean_prediction_error` are null.
- A non-finite embedding does not reach the change score: Topos and Audition report a change of 0 for it, as on a first report, and leave the previous embedding and the change history as they were, so the next reading is compared with the last finite one.
- Topos's habituator does not observe a skipped embedding; the report carries the last habituation score (null before the first finite embedding). A non-finite `latent`, `peripheral` or `foveal` vector is published as null, so a report carries no non-finite number. No module reads these vectors from the payload, and the Nexus privacy filter already drops them.
- `widened_copy` starts a shadow in the re-seeding state when the live model holds no prediction, so a positive-control shadow built right after a skipped reading re-seeds with the live model instead of scoring and learning where the live model does not.

## Capabilities

### Modified Capabilities

- `topos-predictive`: a non-finite clip latent is skipped by the forward model and the change score.
- `audition-predictive`: a non-finite acoustic embedding or tone feature vector is skipped by the forward model, and a non-finite acoustic embedding by the change score.

## Impact

- `kaine/modules/topos/forward.py`, `kaine/modules/audition/forward.py`, `kaine/modules/topos/module.py`, `kaine/modules/audition/module.py`, tests.
- Finite readings behave exactly as before.
