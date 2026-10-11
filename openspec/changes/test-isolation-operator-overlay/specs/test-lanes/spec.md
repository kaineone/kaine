## ADDED Requirements

### Requirement: Tests are isolated from the operator's local overlay
A test SHALL NOT read the maintainer's git-ignored `config/kaine.operator.toml`, unless the test exists to exercise the overlay and supplies its own. A test whose skip condition checks for a file SHALL load that file from the same location it checked.

#### Scenario: An overlay that enables state encryption does not fail the CLI tests
- **WHEN** the repository has a `config/kaine.operator.toml` that enables state encryption with no key available, and the research CLI tests run
- **THEN** they pass as they do on a host with no overlay

#### Scenario: A provisioned encoder test loads what it checked
- **WHEN** the real encoder weights exist under the real data root and the real-weight encoder test runs
- **THEN** it loads the weights from that data root rather than from the per-test one
