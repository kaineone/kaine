## ADDED Requirements

### Requirement: The valuation module is held and off by default
KAINE SHALL provide a `valuation` module selected by `[modules].valuation`, which SHALL be `false` in the shipped `config/kaine.toml` and in the first-configuration profile. With the module off, no valuation object SHALL be built and no other module's behaviour SHALL change.

#### Scenario: Shipped configuration
- **WHEN** the cycle boots with the shipped configuration
- **THEN** no valuation module is built and no `valuation.*` event is published

### Requirement: Relief is measured against the no-response trajectory
For each deficit and each affect update interval, the valuation module SHALL take the step relief as the amount by which the deficit's published no-response value exceeds its actual value, floored at zero. Relief that the credit rule labels `other` SHALL NOT enter the step relief.

#### Scenario: Perceptual novelty relieves boredom
- **WHEN** boredom falls only because perceptual novelty that the credit rule labels `other` arrives
- **THEN** the step relief for boredom is zero

#### Scenario: An engaging intent relieves boredom
- **WHEN** an intent not about a drive relieves boredom by `rho_eng`
- **THEN** the step relief for boredom equals the drop below the no-response value

### Requirement: Relief is credited to intents by eligibility
Each intent of kind speak, think, stir or act on the action-selection stream SHALL open an eligibility trace that decays with time constant `Delta_v` and closes at three time constants. Each step relief SHALL be divided among the open traces in proportion to their current values. A rest intent SHALL open no trace. On a broadcast without an intent, at most once per `Delta_v`, the module SHALL open a trace for the pseudo-kind `none`.

#### Scenario: Two intents share a window
- **WHEN** a think intent and a speak intent are both open with equal trace values when a relief step arrives
- **THEN** each is credited half of that step's relief

#### Scenario: A rest intent
- **WHEN** the action-selection module emits a rest intent
- **THEN** the valuation module opens no trace for it

### Requirement: The outcome model learns expected relief per drive
For each context, intent kind and deficit, the module SHALL keep an expected relief `Q`, a count and an uncertainty, all starting at zero, and SHALL update `Q` by `Q <- Q + alpha (relief - Q)` when a trace closes. The context SHALL be the dominant deficit at the intent paired with the source class of the coalition member the intent is about. No expected relief SHALL be written in by configuration or code.

#### Scenario: An authored relief is recovered
- **WHEN** an offline stream in which every think intent relieves restlessness by the authored rule is replayed
- **THEN** the expected restlessness relief of think converges to the authored relief within its uncertainty

#### Scenario: Nothing is assumed
- **WHEN** a context and kind have never been observed
- **THEN** their expected relief is zero and their count is zero

### Requirement: Value depends on the current deficits
The module SHALL compute the value of an intent kind in a context as `F(D) - F(max(0, D - Q))`, with `F(D) = (sum_d D_d^n)^(1/m)` and `n > m > 1`, and SHALL report each kind's advantage over the pseudo-kind `none`. The configuration validator SHALL reject `n <= m` or `m <= 1`.

#### Scenario: The same relief is worth more under greater need
- **WHEN** an intent kind's expected boredom relief is fixed and boredom is higher
- **THEN** its value is higher

#### Scenario: Invalid exponents
- **WHEN** `[valuation]` sets `n = 2` and `m = 2`
- **THEN** the boot fails with a configuration error

### Requirement: Windows around a reset, a freeze or a welfare response are discarded
A trace whose window contains a sleep onset, a sleep reset, a freeze by any holder, or a welfare protective response SHALL be discarded without updating any table, and the discard SHALL be counted by reason in `valuation.values`.

#### Scenario: A sleep reset inside a window
- **WHEN** a sleep starts and resets the deficits while a think trace is open
- **THEN** the think trace is discarded and the count of windows discarded for sleep rises by one

#### Scenario: A welfare freeze inside a window
- **WHEN** the welfare monitor places a freeze while a trace is open
- **THEN** the trace is discarded and no expected relief changes

### Requirement: The module publishes content-free values
At every stage the module SHALL publish `valuation.values` on a diagnostics stream that the workspace does not score, carrying counts, advantages, uncertainties and discard counts only.

#### Scenario: Values are not scored
- **WHEN** a `valuation.values` event is published
- **THEN** the workspace scores no candidate from it

### Requirement: The prediction error competes only at the compete stage
With `[valuation].stage = "compete"`, on each closed window whose count has reached `n_min`, the module SHALL publish `valuation.surprise` carrying the intent kind, the drive, the sign of the prediction error and its ratio to the running mean absolute error, at the intensity `graded_intensity(baseline, alert, ratio)`. With `stage = "shadow"` it SHALL publish no `valuation.surprise`.

#### Scenario: Shadow stage
- **WHEN** the module runs with `stage = "shadow"` and a large prediction error occurs
- **THEN** no `valuation.surprise` is published and `valuation.values` records the error statistics

#### Scenario: Compete stage
- **WHEN** the module runs with `stage = "compete"` and a window's relief is three times the running mean absolute error above its expectation
- **THEN** a `valuation.surprise` event is published at the intensity for ratio 3 and carries no text

### Requirement: The learned tables are part of the entity
The tables, counts and uncertainties SHALL be serialized with the module's state, encrypted when state encryption is on, restored on revive, and copied into a fork. A snapshot without them SHALL start from empty tables and say so in the log.

#### Scenario: Revive
- **WHEN** an entity with learned tables is preserved and revived
- **THEN** its tables are the ones it had

#### Scenario: Fork
- **WHEN** a branch is made from a preserved entity
- **THEN** the branch's valuation tables start as a copy of the parent's

### Requirement: The valuation module never touches the welfare path
The valuation module SHALL NOT read or write the welfare monitor's state, the control file, regulation or the sleep trigger, and the welfare observer's records SHALL be identical with the module on and off on the same event stream.

#### Scenario: Welfare records unchanged
- **WHEN** one recorded event stream is replayed through the welfare observer with the valuation module on and with it off
- **THEN** the two `affect_welfare` records are identical
