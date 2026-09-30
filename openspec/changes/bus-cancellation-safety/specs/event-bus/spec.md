## ADDED Requirements

### Requirement: Bus calls do not lose a cancellation
Every `AsyncBus` operation, and every call made through `AsyncBus.client`, SHALL
raise `asyncio.CancelledError` when the calling task was cancelled during the
call and the Redis client caught that cancellation and returned normally. The
bus SHALL detect this by the task's cancellation count rising during the call.
It SHALL NOT raise when the count was already non-zero before the call and did
not rise, so cleanup that runs after a task caught its own cancellation can
still use the bus. Results and behaviour SHALL be unchanged when cancellation is
delivered normally.

#### Scenario: A swallowed cancellation ends a workspace subscription
- **WHEN** a task iterating `subscribe_workspace_block` is cancelled and the
  Redis client swallows the `CancelledError`, returning an empty reply
- **THEN** the subscription raises `CancelledError`, and the task finishes as
  cancelled

#### Scenario: Module shutdown is bounded despite a swallowed cancellation
- **WHEN** a module's workspace loop is subscribed and the bus client swallows
  the cancellation that `shutdown()` sends
- **THEN** `shutdown()` still returns promptly

#### Scenario: Cleanup after a caught cancellation still uses the bus
- **WHEN** a task catches its own `CancelledError` and then publishes to the bus
  before re-raising
- **THEN** the publish completes and returns its entry id
