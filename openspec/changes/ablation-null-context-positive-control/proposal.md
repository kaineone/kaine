## Why

Paper §5.4 lists the null-context evaluation behind the planned test's measure, and the measure's positive control, as work to finish in the live cycle before the live runs. Appendix A.8 defines the gain of a report as the error of the processor's prediction under a null context minus its error under the context it held, over its running mean error. The null context keeps the processor's own share and replaces every other source's contribution by its mean over the contexts adopted so far in the run, replaces components 1 to 4 (indices 0 to 3 in the code) by their means, and keeps the age and the two flags.

An audit of the code against A.8 finds the per-report gain (`context_gain`) already built to that definition in Topos, Audition's acoustic path and Soma, with three gaps:

- The context and its null are built by two calls that each read the clock for the age. With a live clock the two ages differ, so the null differs from the context in a component A.8 keeps, and the gain picks up a term that has nothing to do with other modules' contributions.
- §6.2 lists the processors' paired evaluations among a study's records. A report carries its error and the gain but not the error under the null context or the running mean it was divided by, and Soma's running mean cannot be recovered from the research log.
- Soma's forward model skips a non-finite reading but keeps the previous reading's null error and prediction, so Soma would publish a gain from a stale null error against an error of 0, score the next reading against a prediction from two readings back, and average the skipped reading's 0 into its running mean.

The positive control (§6.3, A.8) is not built in this change. The paper leaves open what the synthetic component carries for each processor and how it can carry information about the next input when the prediction is formed before that input exists, whether "IG_j with the component" and "IG_j without it" come from one run or from paired runs, and how the control's minimum effect is set. Those questions go to the operator; the tasks for the control stay open here until they are answered.

## What Changes

- `BroadcastContext.context_and_null(kept_sources)` returns the context and its null from one reading of the clock, so the two share the age and flags exactly. Topos, Audition and Soma use it.
- Each of `topos.report`, `audition.perception` and `soma.report` carries `null_prediction_error` and `mean_prediction_error`, set exactly when `context_gain` is set, so that the gain equals the null error minus the error over the mean. The curated research log copies both, and the post-run range sweep declares them non-negative.
- When Soma's forward model skips a non-finite reading it clears its null error and its stored prediction, context and hidden state, so neither that reading nor the next one reports a gain and the next one makes no update from stale state. Soma leaves the skipped reading out of its running mean error.

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: the null context differs from the held context only in the coalition-level components and other sources' contributions; reports carry the paired evaluations.
- `research-event-log`: the log carries the paired evaluations.

## Impact

- `kaine/modules/context.py`, `kaine/modules/topos/module.py`, `kaine/modules/audition/module.py`, `kaine/modules/soma/module.py`, `kaine/modules/soma/forward.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/log_schema.py`, docs, tests.
- Learning, intensities and the competition are unchanged: the null prediction still never trains a model or enters a score.
