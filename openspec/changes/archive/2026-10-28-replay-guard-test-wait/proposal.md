## Why

`tests/test_effectors_module.py::test_replay_guard_memory_is_bounded` publishes six signed act intents and then sleeps a fixed 0.2 s before it reads the replay guard's high-water mark. Under CI load the effectors module has not consumed all six by then, so the test fails although the guard is correct. Two sibling tests in the same file, `test_replayed_intent_rejected` and `test_replay_guard_survives_light_restart`, read the audit log after the same kind of fixed sleep.

## What Changes

- A test helper polls a condition until it holds or a deadline passes.
- The three replay-guard tests wait for the state they then assert (the high-water mark reaching the last sequence number, the provenance-rejected audit record) instead of sleeping a fixed time. Their assertions are unchanged.
- No production code changes.

## Capabilities

### Modified Capabilities

- `test-lanes`: asynchronous effectors tests wait on the condition they assert.

## Impact

- `tests/test_effectors_module.py` only.
