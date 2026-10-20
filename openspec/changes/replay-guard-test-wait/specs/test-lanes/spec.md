## ADDED Requirements

### Requirement: Asynchronous effectors tests wait on the asserted condition
A test that publishes act intents on the bus and then asserts on the effectors module's replay guard or audit log SHALL wait until the asserted state is observable, polling with a deadline of several seconds, and SHALL NOT rely on a fixed sleep for the module to consume the intents. A guard that never reaches the asserted state SHALL still fail the test once the deadline passes.

#### Scenario: The module is slow to consume the intents
- **WHEN** six signed intents take longer than 0.2 s to be consumed under CI load
- **THEN** `test_replay_guard_memory_is_bounded` waits until the high-water mark reaches 5 and passes

#### Scenario: The guard is broken
- **WHEN** the replay guard stops recording the high-water mark
- **THEN** the test fails after its deadline
