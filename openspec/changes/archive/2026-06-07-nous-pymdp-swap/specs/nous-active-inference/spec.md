## ADDED Requirements

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
