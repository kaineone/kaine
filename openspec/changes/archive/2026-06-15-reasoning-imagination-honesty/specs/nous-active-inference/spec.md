## ADDED Requirements

### Requirement: Inference crash is distinguished from a genuine no_op

Nous SHALL distinguish a non-timeout inference crash from a genuine reasoned
no_op. `EngineResult` SHALL carry `error: bool` and `error_reason: str` fields.
On a non-timeout exception `PymdpEngine.step()` SHALL set `error=True` and log
at `ERROR` level; `timed_out` and `error` SHALL be mutually exclusive — timeouts
are a planned degradation, crashes are unexpected failures.

When `result.error` is set, Nous SHALL publish a `nous.error` diagnostic event
(with `error_reason`, `elapsed_ms`, `num_factors`, `num_actions` in the payload)
and SHALL NOT publish `nous.belief` or `nous.policy` for that cycle — stale
priors held in the engine buffer are NOT a fresh computation and MUST NOT be
re-broadcast as one.

The existing timeout path is unaffected: `timed_out=True` results continue to
trigger `nous.timeout` and publish belief/policy from the last posterior.

#### Scenario: Inference crash emits nous.error, not fabricated belief
- **WHEN** the EFE inference thread raises a non-timeout exception
- **THEN** the engine returns an `EngineResult` with `error=True` and a
  non-empty `error_reason`
- **AND** Nous publishes `nous.error` with the reason in the payload
- **AND** Nous does NOT publish `nous.belief` or `nous.policy` for that cycle

#### Scenario: Timeout still publishes belief and policy
- **WHEN** EFE planning exceeds `efe_timeout_ms`
- **THEN** the engine returns `timed_out=True` and `error=False`
- **AND** Nous publishes `nous.timeout`, `nous.belief`, and `nous.policy`
- **AND** `nous.error` is NOT published

#### Scenario: Crash after a good cycle does not re-broadcast stale belief
- **WHEN** an inference crash occurs on cycle N+1 following a successful cycle N
- **THEN** only one `nous.belief` event exists (from cycle N)
- **AND** one `nous.error` event is published for cycle N+1
