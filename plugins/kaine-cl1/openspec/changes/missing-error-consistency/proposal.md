## Why

KAINE's interoception decides from its forward model's `last_error_defined` whether a reading's prediction error is defined. A reading skipped as non-finite, and the first reading after it, have no defined error: interoception publishes a null `prediction_error` for them and keeps them out of its running error window and out of its learned expected error. `WetwareInteroceptiveModel` has no `last_error_defined`, so interoception treats every error it returns as defined. A skipped reading then publishes 0, enters the window as 0, and leaves the prediction and hidden state from before the skip in place, so the next reading is scored against a stale prediction and updates the readout from it.

## What Changes

- `WetwareInteroceptiveModel` exposes `last_reading_skipped` and `last_error_defined` as the interoception module's built-in forward model does. A non-finite reading clears the stored prediction and the hidden state that produced it, is marked skipped with an undefined error, and returns 0 without a substrate tick or a readout update. The next reading returns 0, has an undefined error and makes no update. The first reading after construction or `reset()` keeps its defined error of 0. `reset()` clears the flags.

## Impact

- `src/kaine_cl1/backends/interoception.py`, `tests/test_interoception_wetware.py`. KAINE's side of the change is `openspec/changes/missing-error-consistency/` in the main tree.
