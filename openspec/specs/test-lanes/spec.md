# test-lanes Specification

## Purpose
How the test suite runs in CI: in parallel on every pull request, with statistical tests over a minute long in a slow lane that runs on main, nightly, and on pull requests that touch the code those tests exercise.

## Requirements

### Requirement: Slow tests run whenever their code changes, and nightly
A statistical test that takes over a minute SHALL carry the `slow` marker. Pull-request CI SHALL skip slow tests unless the pull request changes a path listed in `.github/slow-test-paths.txt`, and SHALL then run them. Pushes to main, a nightly schedule and manual dispatch SHALL run every test, slow ones included. Every file that contains a slow test SHALL be listed in the paths file, and a test SHALL fail when one is not.

#### Scenario: A pull request touches the Active Inference benchmark
- **WHEN** a pull request changes `kaine/evaluation/benchmarks/active_inference/`
- **THEN** CI runs the slow tests as well as the rest of the suite

#### Scenario: A pull request touches unrelated code
- **WHEN** a pull request changes only paths that the slow-paths file does not list
- **THEN** CI runs every test except the slow ones

#### Scenario: A slow test is added without its path
- **WHEN** a test is marked slow in a file the slow-paths file does not list
- **THEN** the slow-lane guard test fails, naming the file

### Requirement: The test suite runs in parallel
CI SHALL run the test suite in parallel, one worker per CPU, keeping each test file on a single worker. The suite SHALL pass in that mode.

#### Scenario: CI runs the suite
- **WHEN** the test workflow runs
- **THEN** pytest runs with `-n auto --dist loadfile`

### Requirement: The suite is a required check and runs for every merge-queue batch
The tests workflow SHALL run on every pull request to `main` without a path filter, and on every merge-queue batch. The CodeQL, import-boundary, red-team and ruff workflows SHALL also run on merge-queue batches. A merge-queue batch SHALL run the slow tests when it changes a path listed in `.github/slow-test-paths.txt`, diffed against the batch's base.

#### Scenario: A pull request changes only OpenSpec files
- **WHEN** a pull request changes only files under `openspec/`
- **THEN** the test suite still runs, so the required pytest check reports a result

#### Scenario: A merge-queue batch touches the Active Inference benchmark
- **WHEN** a merge-queue batch changes `kaine/evaluation/benchmarks/active_inference/`
- **THEN** CI runs the slow tests for that batch as well as the rest of the suite

### Requirement: Tests never write to real KAINE data
The test suite SHALL give every test its own data root and SHALL prevent tests from discovering the host's real disks. A test that changes the checkout's `state/`, or any real data-root candidate known when the session starts, SHALL fail and name the directories it changed. The guards SHALL read directory modification times only, never file contents. They SHALL skip `forks`, `models` and `_archive*`. The real-root guard SHALL stand down, with a warning, while a `kaine.cycle` process is running.

#### Scenario: A test drives the setup wizard to a save
- **WHEN** a test runs the storage step without naming a data root
- **THEN** it sees no real mounts, and its default data root lies inside the test's temporary directory

#### Scenario: A test writes into a real data root
- **WHEN** a test creates or removes a file under a watched real data root
- **THEN** that test fails and names the changed directory
