## Why

`tests/test_setup_web_jobs.py::test_group_kill_reaps_sigterm_ignoring_grandchild_after_cancel`
fails intermittently in the parallel gate and in CI, and it has dropped pull
requests from the merge queue. Every failure is the same assertion: after the
cancel, the test awaits the child process's exit and then reads the job status,
which is still `running`.

The job runner sets the status in its own `_wait` task. That task wakes on the
same process exit as the test, then waits for the output reader to drain the
pipe before it records the result and sets the job's done event. The test reads
the status before `_wait` has run that far. Under load the gap is wide enough to
lose the race about once in thirty runs (6 failures in 200 runs with 32 CPU
burners on a 32-core host). The runner behaves as designed: a job reports its
final status only once its output is complete, and it does so a few event-loop
turns after the process exits. The defect is in the test, which treats process
exit as job completion.

The shutdown variant of the test reads the status the same way. It did not fail
in 200 runs, because its grandchild poll usually sleeps once before the read,
but the race is the same.

## What Changes

- Both group-kill tests wait for the job's done event, which the runner sets
  after it records the final status, before they read the status.
- They assert the exact final status the runner reports for each path:
  `cancelled` after a cancel, `failed` after a shutdown.
- No production code changes.

## Capabilities

### Modified Capabilities

- `first-run-wizard`: a cancelled or shutdown setup job reports its final
  status once its output is complete, and the tests check that status without
  racing the runner.

## Impact

- `tests/test_setup_web_jobs.py` only.
