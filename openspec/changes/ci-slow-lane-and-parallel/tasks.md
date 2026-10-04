## 1. Parallel runs
- [x] 1.1 `pytest-xdist` in the `test` extra; CI runs `-n auto --dist loadfile`. Locally the suite passes with 4 workers.

## 2. Slow lane
- [x] 2.1 Register the `slow` marker; mark the Active Inference headline verdict test.
- [x] 2.2 CI runs slow tests on main, nightly, on dispatch, and on pull requests touching `.github/slow-test-paths.txt` paths.
- [x] 2.3 The merge tooling stops on a red nightly (operator tooling, outside the repository).

## 3. Tests and docs
- [x] 3.1 Shrink the reproducibility test and compare every reported metric.
- [x] 3.2 `tests/test_slow_lane.py` guards the lane's wiring.
- [x] 3.3 The contributing docs describe parallel runs and the slow lane.
