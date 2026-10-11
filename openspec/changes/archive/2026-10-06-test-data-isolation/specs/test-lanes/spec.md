## ADDED Requirements

### Requirement: Tests never write to real KAINE data
The test suite SHALL give every test its own data root and SHALL prevent tests from discovering the host's real disks. A test that changes the checkout's `state/`, or any real data-root candidate known when the session starts, SHALL fail and name the directories it changed. The guards SHALL read directory modification times only, never file contents. They SHALL skip `forks`, `models` and `_archive*`. The real-root guard SHALL stand down, with a warning, while a `kaine.cycle` process is running.

#### Scenario: A test drives the setup wizard to a save
- **WHEN** a test runs the storage step without naming a data root
- **THEN** it sees no real mounts, and its default data root lies inside the test's temporary directory

#### Scenario: A test writes into a real data root
- **WHEN** a test creates or removes a file under a watched real data root
- **THEN** that test fails and names the changed directory
