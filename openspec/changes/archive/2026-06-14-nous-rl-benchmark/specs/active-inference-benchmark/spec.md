## ADDED Requirements

### Requirement: Offline AIF-vs-RL benchmark on matched bounded tasks
The system SHALL provide an offline benchmark harness that runs Nous's
active-inference engine and a reinforcement-learning baseline on a shared suite
of bounded discrete decision tasks, matched on observation model and reward.
The harness SHALL run headless without an entity boot and without attaching to
the live cognitive loop or event bus. The active-inference agent SHALL reuse
the same pymdp generative-model construction that the live Nous module uses.

#### Scenario: Benchmark runs without a live entity
- **WHEN** the benchmark CLI is invoked
- **THEN** it constructs synthetic discrete POMDP tasks and runs both agents on them
- **AND** it does NOT require a running entity, a bus connection, or a cognitive cycle

#### Scenario: Agents are matched on observation and reward
- **WHEN** a task is run by both agents
- **THEN** the RL agent's scalar reward and the AIF agent's preference vector `C`
  encode the same task reward over the same observation model
- **AND** each result record discloses the matching used

### Requirement: Task suite isolates the value of epistemic action
The task suite SHALL include at least one *epistemic* task, in which a hidden
state must be revealed by an information-seeking action before the rewarding
action pays off, and at least one *exploitation* task with no hidden state. The
reported "value of epistemic action" SHALL be derived from performance on the
epistemic tasks and the gap between epistemic and exploitation performance.

#### Scenario: Epistemic task requires information-seeking
- **WHEN** the epistemic task is run
- **THEN** the reward-maximizing policy requires taking the probe action before committing
- **AND** the harness records each agent's probe rate and timing

#### Scenario: Exploitation task has no hidden state
- **WHEN** the exploitation task is run
- **THEN** the optimal policy is a fixed observation→action mapping requiring no probing

### Requirement: Reported metrics and a reportable verdict
For each task and aggregated across seeds, the harness SHALL report decision
quality (asymptotic reward), sample efficiency (steps/episodes to a performance
threshold and/or cumulative regret), and value of epistemic action. It SHALL
classify each task and the suite overall as WIN, NULL, or NEGATIVE using a
statistical test across seeds. NULL (AIF statistically matches the baseline) and
NEGATIVE (AIF underperforms) SHALL be first-class reportable outcomes, surfaced
plainly rather than treated as harness failures.

#### Scenario: A null result is reported as null
- **WHEN** the AIF and RL decision-quality distributions are not separable
  beyond the configured significance level and effect size
- **THEN** the verdict for that task is NULL
- **AND** the JSONL record and CLI summary state NULL explicitly

#### Scenario: A negative result is reported as negative
- **WHEN** the AIF decision-quality distribution is significantly lower than the baseline's
- **THEN** the verdict for that task is NEGATIVE

#### Scenario: A win requires significance and effect size
- **WHEN** the AIF decision-quality distribution is significantly higher than the
  baseline's beyond the configured minimum effect size
- **THEN** the verdict for that task is WIN

### Requirement: Seeded and reproducible
Every benchmark run SHALL be seeded. Result records SHALL carry the task, seed,
agent, the baseline's hyperparameters, raw per-episode returns, and computed
metrics, such that re-running with the same seeds reproduces the verdict.

#### Scenario: Same seeds reproduce the verdict
- **WHEN** the benchmark is run twice with the same seed set
- **THEN** the per-task and aggregate verdicts are identical
