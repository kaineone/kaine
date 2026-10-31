## ADDED Requirements

### Requirement: The learned report policy moves each bar by evidence within a bound
With `[action_selection].policy = "learned_report"`, the action-selection module SHALL use, for each intent kind and context, the effective bar `clip(theta_k0 - b_max * w * tanh(A / A_scale), theta + m_theta, 1)`, where `theta_k0` is the kind's authored bar, `A` the kind's learned advantage in that context, and `w = N / (N + N_0)` with `N` its count. The shipped policy SHALL remain `self_initiated_report`.

#### Scenario: No evidence
- **WHEN** a kind has a count of zero in the current context
- **THEN** its effective bar equals its authored bar

#### Scenario: A kind that relieves need
- **WHEN** think has a positive advantage and a count of `N_0` in the current context
- **THEN** its effective bar is lower than 0.45 by `b_max * 0.5 * tanh(A / A_scale)`

#### Scenario: The floor above access
- **WHEN** a kind's advantage would move its bar below `theta + m_theta`
- **THEN** its effective bar is `theta + m_theta`

### Requirement: The learned report policy keeps the report rule's guards
The learned report policy SHALL apply the in-flight guards, the guard timeout, the refractory intervals and the signature check of the self-initiated report rule unchanged, and SHALL emit at most one intent per accessed broadcast.

#### Scenario: A guard is armed
- **WHEN** a speak intent is in flight and speak clears its effective bar
- **THEN** no speak intent is emitted

### Requirement: The learned report policy chooses among eligible kinds by advantage
When more than one kind clears its effective bar and passes its guards, the learned report policy SHALL choose one with probability proportional to `exp(A / tau)` using a generator seeded from the run seed, treating a kind whose count is below `n_min` as having advantage zero. When every eligible kind's advantage is zero it SHALL choose in the order speak, think, act.

#### Scenario: No history
- **WHEN** a broadcast is processed by the learned report policy with empty valuation tables
- **THEN** the emitted intent is the one the self-initiated report policy emits on the same broadcast

#### Scenario: Seeded choice
- **WHEN** the same broadcast sequence and the same tables are processed twice with the same run seed
- **THEN** the same intents are emitted

### Requirement: Rest, welfare and operator-response paths stay outside learning
The learned report policy SHALL NOT bias rest intents from regulation, the planning module or the developmental rest, the welfare net or any freeze, the response to operator speech, the developmental stir's trigger, or the interrupt bar. The configuration validator SHALL reject an interrupt bar at or below `theta_sp0 + b_max`.

#### Scenario: Regulation requests rest
- **WHEN** emotion regulation reaches tier 3 while the learned report policy is selected
- **THEN** the sleep request is the one the fixed policy would produce on the same stream

#### Scenario: An interrupt bar too low
- **WHEN** `[action_selection.learned]` sets `b_max = 0.1` and the interrupt bar is 0.65
- **THEN** the boot fails with a configuration error

### Requirement: Effective bars are recorded
The content-free research log SHALL record each kind's effective bar in every context with a nonzero count at every viewing boundary, and the run manifest SHALL record the policy and its parameters.

#### Scenario: A viewing ends
- **WHEN** a viewing ends under the learned report policy
- **THEN** the research log holds the effective bars and counts for that viewing and no utterance text
