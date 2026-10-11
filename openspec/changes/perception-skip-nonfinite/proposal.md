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
- A reading has a defined error unless it was skipped or is the first reading after a skip, which has no prediction to be scored against. Paper A.2 sets the error of the very first reading to 0 ("The error is ν_t = ‖z_t − ẑ_t‖₂, with ν₁ = 0") and takes the running ratio over the window of the errors ν_t; A.5 does the same for Soma ("with ν^Som_t = 0 on the first reading"). The boot reading's 0 therefore stays in the window, and only readings without a defined error are kept out. The forward models expose this as `last_error_defined`, and Topos, Audition (acoustic and tone paths) and Soma append to their running windows only when it is true. Otherwise periodic gaps would fill the window with zeros, lower the mean and make real readings alert.
- A report without a defined error publishes `prediction_error` as null (`topos.report`, `audition.perception`, `audition.emotion`, `audition.transcription`, `soma.report`), so Thymos does not pool a made-up 0 into its learning-progress trackers. The welfare observer and the preservation monitor read `soma.report`'s error with `float(...)`; they now treat a null error as no sample, which neither feeds nor ends a sustained-distress episode. Every other reader already skips a null error or maps it to its default.
- Empatheia passes a null error through and leaves its `mean_prediction_error` average unchanged for an observation without a defined error, including the transcription placeholder fold, which used to feed it 0. The workspace-mediation benchmark records a skipped error as null.
- A run of missing readings is not yet reported as a welfare signal. The welfare observer's gray-zone event (`welfare.gray_zone`) has a closed set of four categories, and the protective monitor acts on repeated gray-zone events of any category, so a new category for a blind sensor would also be able to preserve and pause or end the entity. That is a welfare-policy decision and is left to a follow-up change.
- `widened_copy` starts a shadow in the re-seeding state when the live model holds no prediction, so a positive-control shadow built right after a skipped reading re-seeds with the live model instead of scoring and learning where the live model does not.

## Capabilities

### Modified Capabilities

- `topos-predictive`: a non-finite clip latent is skipped by the forward model and the change score.
- `audition-predictive`: a non-finite acoustic embedding or tone feature vector is skipped by the forward model, and a non-finite acoustic embedding by the change score.
- `soma-predictive`: a skipped reading and the reading after it publish no error and stay out of the window; welfare consumers treat a null error as no sample.
- `empatheia`: an observation without a defined error leaves the error average alone.
- `topos`: `latent`, `peripheral`, `foveal`, `habituation_score` and `prediction_error` can be null.

## Impact

- `kaine/modules/topos/forward.py`, `kaine/modules/audition/forward.py`, `kaine/modules/soma/forward.py`, `kaine/modules/topos/module.py`, `kaine/modules/audition/module.py`, `kaine/modules/soma/module.py`, `kaine/evaluation/observers/welfare_observer.py`, `kaine/cycle/preservation_monitor.py`, `kaine/modules/empatheia/agent.py`, `kaine/modules/empatheia/module.py`, `kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py`, docs, tests.
- Finite readings behave exactly as before.
