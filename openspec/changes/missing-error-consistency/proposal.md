## Why

Since `perception-skip-nonfinite`, a reading without a defined prediction error (a reading skipped as non-finite, and the first reading after it) publishes `prediction_error` as null and stays out of its module's running error window. Two places still treat a missing error as a 0.

The CL1 plugin's wetware Interoception backend, `WetwareInteroceptiveModel`, returns 0 for a non-finite reading but has no `last_error_defined`, so Interoception falls back to its default and treats every error as defined. On that backend a skipped reading still publishes 0, puts 0 in the running window, and leaves its prediction and hidden state in place, so the next reading is scored against the prediction made before the skip and updates the readout from it. Interoception's built-in forward model clears both and marks the reading and the next one as having no defined error. Because the wetware model exposes no per-channel residuals, Interoception also feeds its scalar error to the learned expected error, so the skipped reading's 0 teaches the expected-error estimate as well; the built-in model reports null residuals there and teaches nothing.

`EmpatheiaMergeStrategy` averages each `behavioral_summary` key across two forks with a 0.0 default for a side that lacks it. Social cognition leaves `mean_prediction_error` unset for an agent that never had a defined error, so merging such a fork averages a made-up 0 into the other fork's value, and a stored null would fail the `float(...)` conversion.

## What Changes

- `WetwareInteroceptiveModel` gets the built-in model's contract: `last_reading_skipped`, `last_error_defined` and the skip itself. A non-finite reading clears the stored prediction and the hidden state behind it, marks the reading skipped and its error undefined, and returns 0 without a substrate tick or a readout update. The next reading returns 0 with an undefined error and makes no update. The first reading after construction or `reset()` keeps its defined error of 0 (paper A.5). `reset()` clears the flags.
- Interoception reports an unexpected error of 0 and leaves its expected-error estimates unchanged for a reading without a defined error from any forward model, including one without per-channel residuals.
- `EmpatheiaMergeStrategy` treats a missing or null `behavioral_summary` entry on one side as absent. A key defined on both sides keeps the count-weighted average. A key defined on one side takes that side's value. A key defined on neither side stays absent. When the sides that hold a value have no interactions, their plain mean is used.
- The CL1 plugin's `soma-wetware-backend` spec is updated in the plugin's own OpenSpec tree (`plugins/kaine-cl1/openspec/changes/missing-error-consistency/`).

## Capabilities

### Modified Capabilities

- `empatheia`: a missing or null behavioural-summary entry is absent in a merge.
- `soma-predictive`: a reading without a defined error reports no unexpected error and teaches the expected error nothing.
- `soma-wetware-backend` (CL1 plugin): the wetware model skips a non-finite reading as the built-in model does and exposes `last_error_defined`.

## Impact

- `plugins/kaine-cl1/src/kaine_cl1/backends/soma.py`, `kaine/modules/soma/module.py`, `kaine/lifecycle/strategies.py`, docs, tests.
- Finite readings and merges of fully defined summaries behave exactly as before. The plugin's version is unchanged; it has never been bumped per change.
