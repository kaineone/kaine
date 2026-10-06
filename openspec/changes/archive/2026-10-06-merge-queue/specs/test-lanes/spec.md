## ADDED Requirements

### Requirement: The suite is a required check and runs for every merge-queue batch
The tests workflow SHALL run on every pull request to `main` without a path filter, and on every merge-queue batch. The CodeQL, import-boundary, red-team and ruff workflows SHALL also run on merge-queue batches. A merge-queue batch SHALL run the slow tests when it changes a path listed in `.github/slow-test-paths.txt`, diffed against the batch's base.

#### Scenario: A pull request changes only OpenSpec files
- **WHEN** a pull request changes only files under `openspec/`
- **THEN** the test suite still runs, so the required pytest check reports a result

#### Scenario: A merge-queue batch touches the Active Inference benchmark
- **WHEN** a merge-queue batch changes `kaine/evaluation/benchmarks/active_inference/`
- **THEN** CI runs the slow tests for that batch as well as the rest of the suite
