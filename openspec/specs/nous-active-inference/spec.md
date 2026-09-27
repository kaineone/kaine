# nous-active-inference Specification

## Purpose
TBD - created by archiving change nous-pymdp-swap. Update Purpose after archive.

## Requirements

### Requirement: pymdp 1.0 (JAX) active-inference engine
Nous SHALL perform belief updating and policy selection via expected-free-energy
minimization using **pymdp 1.0 (JAX)** over a discrete generative model derived
from workspace content. The engine SHALL be reachable behind an
`ActiveInferenceEngine` protocol so a `FakeEngine` can substitute in tests, and a
green build SHALL NOT require the OpenNARS-for-Applications binary.

The `[reasoning]` optional extra SHALL include both `pymdp>=1.0` and `jax[cpu]` so
the JAX backend is available without a CUDA installation.

#### Scenario: Belief update changes the posterior
- **WHEN** the engine receives an observation that favors a hidden state
- **THEN** the posterior over hidden states shifts toward that state

#### Scenario: Policy selection minimizes expected free energy
- **WHEN** the engine evaluates candidate policies
- **THEN** the selected policy is the one with the lowest expected free energy

#### Scenario: Build needs no NAR binary
- **WHEN** the unit suite runs without `external/OpenNARS-for-Applications`
  present
- **THEN** the Nous tests pass using the `FakeEngine`

### Requirement: Explicit v1 action space
Nous SHALL define an explicit discrete action space for v1:
`{no_op, request_think, request_speak, request_maintenance}`. Epistemic actions
(`request_think`) are information-seeking intents that Nous can select without
Praxis whitelisting them, because they remain internal to the cognitive loop. The
B-matrix (state-transition) SHALL be indexed over this four-element action space.
EFE policy selection MUST have at least this action space to evaluate policies
over; the absence of a Praxis whitelist is therefore NOT a blocker for v1.

#### Scenario: Action space covers epistemic and communicative actions
- **WHEN** the engine initialises its generative model
- **THEN** the B-matrix has exactly four action dimensions matching the v1 space

#### Scenario: Epistemic actions do not require Praxis whitelist
- **WHEN** the engine selects `request_think`
- **THEN** the resulting `intent.act` is handled within the cognitive loop without
  requiring a Praxis whitelist entry

### Requirement: EFE planning is bounded
EFE planning MUST NOT run unbounded in the 300 ms cognitive-cycle budget. Three
guards SHALL be in place before the engine is enabled in production:

1. A **pre-build benchmark task** runs EFE on the target CPU with the configured
   complexity envelope (factors × states × actions × horizon) and records the
   median latency; the build MUST fail if median exceeds 200 ms.
2. A **hard timeout guard** in `engine.py`: if EFE planning exceeds a configured
   `efe_timeout_ms` (default 250), the engine SHALL return the last computed
   posterior and emit a `nous.timeout` diagnostic event rather than blocking the
   cycle.
3. A **complexity envelope** (factors, max states per factor, actions, horizon) is
   declared in `[nous]` config and validated at startup; the config validator SHALL
   reject envelopes whose estimated worst-case step count exceeds a threshold.

#### Scenario: Pre-build benchmark catches slow configurations
- **WHEN** the configured complexity envelope causes EFE to exceed 200 ms on the
  target CPU
- **THEN** the benchmark task exits non-zero and the build does not proceed

#### Scenario: Timeout guard prevents cycle overrun
- **WHEN** EFE planning exceeds `efe_timeout_ms` during a live cycle
- **THEN** the engine returns the most recent posterior and emits `nous.timeout`
- **AND** the cognitive cycle continues without blocking

#### Scenario: Config validator rejects oversized envelopes
- **WHEN** a `[nous]` config declares a factors × states × actions × horizon
  product that exceeds the complexity threshold
- **THEN** `make_nous` raises a `ConfigurationError` at startup

### Requirement: Preserved belief contract plus policy output
Nous SHALL continue to publish `nous.belief` events with the existing payload
shape (`statement`, `kind`, `frequency`, `confidence`) so existing consumers are
unaffected, with semantics redefined (statement = dominant latent-factor label,
frequency = posterior expectation, confidence = posterior certainty). Nous SHALL
additionally publish `nous.policy` events carrying the selected policy and its
expected free energy.

#### Scenario: Belief event keeps its shape
- **WHEN** Nous publishes a belief
- **THEN** the `nous.belief` payload contains `statement`, `kind`, `frequency`,
  and `confidence`

#### Scenario: Policy is published
- **WHEN** the engine selects a policy
- **THEN** a `nous.policy` event is published containing `expected_free_energy`

### Requirement: Epistemic actions ride the intent path
Nous SHALL emit any chosen action as an `intent.act` event through the existing
Volition/intent path and SHALL NOT invoke effectors directly, so that Syneidesis
inhibition and Praxis whitelists remain in control of all outward action.

#### Scenario: Action becomes an intent, not a direct call
- **WHEN** the engine selects an information-seeking action
- **THEN** Nous publishes an `intent.act` event and makes no direct effector call

### Requirement: FaithfulRenderer templates for nous events
The FaithfulRenderer SHALL include templates for `nous.belief` and `nous.policy`
events so they are rendered in human-readable form when they enter the conscious
coalition or appear in evaluation logs.

#### Scenario: nous.belief renders as a readable statement
- **WHEN** a `nous.belief` event is passed to the renderer
- **THEN** the output contains the latent-factor label and a formatted certainty
  value, not a raw dict repr

#### Scenario: nous.policy renders with EFE value
- **WHEN** a `nous.policy` event is passed to the renderer
- **THEN** the output contains the selected policy name and the expected free
  energy value

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

### Requirement: The restored posterior reaches the engine
When Nous is restored from a snapshot, the preserved posterior SHALL become both the module's last posterior and its inference engine's fallback posterior, so a degraded step after a revive (a planning timeout or crash) reports the preserved belief rather than the uniform prior. A posterior whose shape does not match the model's factors SHALL be ignored with a warning.

#### Scenario: A degraded first step after revive
- **WHEN** Nous is restored with a posterior and its first planning step times out
- **THEN** the step reports the restored posterior

#### Scenario: A mismatched posterior
- **WHEN** the snapshot's posterior has the wrong number of factors
- **THEN** the engine's fallback is left as it was and a warning is logged

### Requirement: Per-action expected free energy is correct at any planning horizon
Nous SHALL report, for each action, the lowest expected free energy among the policies whose first action is that action, SHALL choose the first action of the policy with the lowest expected free energy, and SHALL publish the configured planning horizon with its policy event.

#### Scenario: A two-step horizon
- **WHEN** Nous plans with a horizon of 2
- **THEN** each action's reported EFE is the best EFE of the two-step policies beginning with it, and the published horizon is 2

### Requirement: Nous's actions have consequences it learns
Nous's generative model SHALL let every perceptual factor's transitions depend on the action taken, SHALL begin with the same broad, uncertain prior belief about every action's consequences, and SHALL learn those consequences from its own experience by updating its transition beliefs after each step with the action it took and the states it inferred before and after. No action's effect SHALL be written into the model.

#### Scenario: A consequence is learned
- **WHEN** one action reliably precedes a rise in salience over repeated steps
- **THEN** Nous's transition belief for that action concentrates on the rising transition

### Requirement: Uncertainty about its own actions drives exploration
Nous's expected free energy SHALL include the information to be gained about its actions' consequences, so that actions whose effects it is less sure of are worth trying, and its choices SHALL NOT collapse to a single action while its model of those consequences is uncertain.

#### Scenario: A new being samples its actions
- **WHEN** a being with an unlearned model of its actions steps through ordinary observations
- **THEN** it chooses more than one action

### Requirement: Belief carries over and the learned model is preserved
Each step's prior SHALL be the previous posterior propagated through the learned transitions under the action taken. Nous's learned transition beliefs and carried belief SHALL be part of its serialized state, and revive SHALL restore them; a snapshot without them SHALL start from the prior and say so in the log.

#### Scenario: Revive keeps the being's sense of agency
- **WHEN** a being is preserved and revived
- **THEN** its learned transition beliefs and carried belief are the ones it had, and its next decision is the one it would have made
