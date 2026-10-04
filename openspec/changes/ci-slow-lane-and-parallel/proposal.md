# Parallel CI and a slow-test lane

## Why

Pull requests merge one at a time, because branch protection requires each to be up to date with main, and each waited about 34 minutes for the test job. Merging is therefore the bottleneck for every change.

The complexity audit (O3) proposed a "breadth" lane for the tests of disabled modules. Measurement showed those tests (Mundus and Praxis, 99 tests) take 3.3 seconds in total, so that lane would save nothing; it was never built.

The time goes elsewhere:
- **Serial execution.** The suite of about 6,400 tests runs one test at a time.
- **Two statistical benchmark tests** take about 190 seconds each locally.

On 2026-10-04 the operator chose a slow lane plus parallel CI.

## What changes

- **Parallel runs.** `pytest-xdist` joins the `test` extra. CI runs `pytest -n auto --dist loadfile`, with each test file kept on one worker.
  - Locally, with 4 workers, the suite without slow tests passes in 2.5 minutes, against about 17 serially.
  - All 6,375 tests pass, and the largest worker peaks at 4.5 GB.
- **The `slow` marker.** It is registered for statistical tests over a minute long. The Active Inference headline verdict test (`test_epistemic_task_verdict_is_win`) carries it.
- **When slow tests run.** A pull request runs them only when it changes a path in `.github/slow-test-paths.txt`. Pushes to main, a nightly schedule and manual dispatch always run them. The merge tooling stops merging when the latest nightly failed.
- **The reproducibility benchmark test** runs a smaller configuration twice, because determinism does not depend on scale. It now compares every reported metric, not only the verdicts, and takes 45 seconds instead of 187.
- **The guard test `tests/test_slow_lane.py`:**
  - every slow-marked test file is listed in the paths file;
  - the patterns compile and none matches everything;
  - the marker is registered;
  - the workflow wiring is in place.
- The contributing docs describe parallel runs and the slow lane.

## Known rare flake

`tests/test_nous_engine.py::test_real_pymdp_engine_rejects_mismatched_posterior` failed once in about nine full parallel runs on 2026-10-04. Eight later runs passed: five targeted runs of the Nous and Active Inference tests, and three full-suite runs. The failing assertion was not captured. The test relies on a 0.001 ms planning timeout always expiring; the engine's timeout path looks sound. If it recurs in parallel CI, the job log names the assertion, and it gets fixed then.

## Impact

- **CI:** every non-slow test still runs on every pull request. The slow test runs whenever its code changes, on every merge to main, and nightly.
- **Research:** none.
