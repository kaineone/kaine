## ADDED Requirements

### Requirement: A hang guard in a test is a deadlock bound
A timeout that a test wraps around an operation to catch a hang SHALL be a named deadlock bound, generous enough that the operation's normal cost in a long-running test process cannot reach it. A test SHALL NOT use such a timeout as a speed bound. The suite SHALL pass when run serially in one process as well as in parallel.

#### Scenario: Unload after JAX-heavy tests
- **WHEN** the whole suite runs serially in one process and a reversible-unload test runs after the active-inference and world-model tests
- **THEN** its unload and close waits complete within the deadlock bound and the test passes

#### Scenario: A real hang still fails
- **WHEN** an unload or close never completes
- **THEN** the test fails at the deadlock bound
