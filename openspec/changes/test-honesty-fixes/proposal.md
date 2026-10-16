## Why

A review of placeholders and workarounds found three tests that look like coverage and are not:

- `test_merger_from_name_output_dir_under_data_root` reads `merger.cfg`, but `TiesDareAdapterMerger` keeps its configuration in `_config`. The test skips on every host, including hosts with PEFT installed, so it never checks the output directory.
- `test_real_internvideo_next_produces_768_from_16_frame_clip` checks for the weights in the import-time models directory, then builds the encoder with no `weights_dir`, so the loader resolves the per-test data root and raises `FileNotFoundError` on a host that has the weights.
- Eight reversible-unload tests in `test_embedder_reversible_unload.py` and `test_speech_reversible_unload.py` fail when the whole suite runs serially in one process. Unload and close run a full `gc.collect()`; after JAX-heavy tests (the active-inference benchmark, the world model) a full collection takes about two seconds, and these tests wrap the calls in two-second `wait_for` timeouts. The timeouts guard against deadlock, not speed.

The social cognition module's `on_workspace` docstring also calls the hook a placeholder reserved for future behaviour. The paper gives the module no use for the broadcast, and the module docs already say so.

## What Changes

- The merger test builds `merger_from_name("ties_dare")`, which constructs the real merger without PEFT, and asserts its `_config.output_dir`; it no longer skips.
- The InternVideo-Next real-encoder test resolves the weights directory to one absolute path, checks it, and passes it to the encoder (a relative path would resolve against the per-test data root).
- The reversible-unload tests use one named deadlock bound, `CLOSE_DEADLOCK_TIMEOUT_S = 30.0`, for every wait on an unload or close, with a comment saying why.
- The social cognition `on_workspace` docstring states what the paper specifies.

## Capabilities

### Modified Capabilities

- `test-lanes`: a timeout that guards against a hang is a deadlock bound, and the suite also passes serially.

## Impact

- `tests/test_storage_lifecycle_paths.py`, `tests/test_vision_internvideo_next.py`, `tests/test_embedder_reversible_unload.py`, `tests/test_speech_reversible_unload.py`, `kaine/modules/social_cognition/module.py` (docstring only).
- No runtime behaviour changes.
