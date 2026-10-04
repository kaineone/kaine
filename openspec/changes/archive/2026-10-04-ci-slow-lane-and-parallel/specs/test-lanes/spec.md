## ADDED Requirements

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
