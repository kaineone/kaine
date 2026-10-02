## ADDED Requirements

### Requirement: Every study command resolves the study directory the same way
`init`, `run`, `status` and `analyse` SHALL resolve `--study-dir` under the installed data root in the same way, so a study created by `init` is found by the other commands from any working directory.

#### Scenario: A study is found from another directory
- **WHEN** a data root is installed, `init` creates `studies/s1`, and `status --study-dir studies/s1` runs from a different working directory
- **THEN** `status` reads the study `init` created
