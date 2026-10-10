## Why

`tests/test_setup_footprint.py::test_measure_callable_in_child_uses_result_before_join_timeout`
fails intermittently in CI and dropped a pull request from the merge queue on
2026-10-10. It gives the spawned child 2 seconds to start, import and report.
A spawn-context child on a loaded runner can take longer, so the poll times
out before any result arrives. The test is about what happens after a result
arrives (the 30-second join and the stop that follows), which the poll timeout
does not govern.

## What Changes

- The test gives the child 60 seconds to report. Its behaviour after the
  report is unchanged.

## Capabilities

### Modified Capabilities

- `dynamic-hardware`: the footprint measurement's test is stable under load.

## Impact

- `tests/test_setup_footprint.py` only.
