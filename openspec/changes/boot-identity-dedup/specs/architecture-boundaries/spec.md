## ADDED Requirements

### Requirement: A module defines each top-level name once
No module under `kaine/` SHALL define the same top-level function or class name more than once, apart from one definition in each branch of a conditional. A test SHALL check this over the package.

#### Scenario: A duplicate definition
- **WHEN** a module under `kaine/` defines a top-level function twice
- **THEN** the test fails and names the module, the function and both line numbers
