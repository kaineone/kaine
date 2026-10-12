## 1. Skip a non-finite reading

- [x] 1.1 `LatentForwardModel.step` and `AuditoryForwardModel.step` skip a non-finite input with no buffer append and no weight update, clear the stored prediction, null prediction, context and null error, and mark the reading skipped
- [x] 1.2 `widened_copy` starts the copy re-seeding its hindsight pairing when the live model holds no prediction
- [x] 1.3 The vision and audition modules keep a skipped reading out of their running error windows and out of the change score
- [x] 1.4 Tests: the skip leaves the buffer and weights untouched; the next report has no gain and the one after has one; the error window and the change history are unchanged; no alert; the hindsight pairing matches the live step across a skip
- [x] 1.5 Docs: the vision and audition module pages describe the skip
- [x] 1.6 The vision module's habituator does not observe a skipped embedding, and a report publishes a non-finite vector as null
- [x] 1.7 Tests: the habituator window is unchanged, no report carries a non-finite number (with and without foveation), and the tone path skips a non-finite feature vector
- [x] 1.8 The forward models expose `last_error_defined`; the vision module, the audition module (both paths) and the interoception module append only defined errors to their windows and publish a null `prediction_error` otherwise
- [x] 1.9 The welfare observer and the preservation monitor treat a null interoception module error as no sample
- [x] 1.10 Tests: periodic gaps keep zeros out of the window; normalised error after a skip; the affect module's trackers unchanged by null errors; welfare consumers keep the distress episode across null errors; the positive control stays paired across a skip in the running module
- [x] 1.11 Docs and specs: the nullable report fields
- [x] 1.12 The social cognition module leaves its error average alone for an observation without a defined error; the mediation benchmark records a skipped error as null
- [x] 1.13 Tests: the protective monitor's timer still fires through null samples, a null mid-batch keeps the loop and the cursor, a missing key keeps its 0 default; the observer fires after a null run and silence; the social cognition module and the benchmark reader keep null
