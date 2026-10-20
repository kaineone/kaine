## REMOVED Requirements

### Requirement: Two-arm workspace-mediation ablation
**Reason**: The offline runner no longer conditions the language organ. The paper retired the organ's utterances as a measure; the harness now compares a workspace-on arm with a pooled arm by information gain.
**Migration**: See "Offline development harness of the workspace-mediation test".

### Requirement: Fair-null rendering discipline
**Reason**: The harness renders nothing for the organ, so a matched rendering budget has nothing to apply to.
**Migration**: See "Pooled arm of the development harness".

### Requirement: Competition capacity in the minimal set
**Reason**: Replaced by the NOT EXERCISED rule of the harness verdict.
**Migration**: See "Development harness verdict".

### Requirement: Primary and secondary measures
**Reason**: Cross-module error coupling, coalition-source entropy and output divergence are retired; the measure is the cross-module broadcast information gain.
**Migration**: See "Development harness measures information gain".

### Requirement: Interoception-salience coverage for measure power
**Reason**: Tied to the retired coupling measure.
**Migration**: See "Development harness verdict".

### Requirement: Reachable adverse verdict
**Reason**: Restated for the information-gain contrast.
**Migration**: See "Development harness verdict".

### Requirement: Scoped reproducibility and multiple-comparisons correction
**Reason**: Restated for the harness and its suite aggregation.
**Migration**: See "Offline development harness of the workspace-mediation test" and "Suite aggregation of the development harness".

## ADDED Requirements

### Requirement: Offline development harness of the workspace-mediation test
The system SHALL provide an offline development harness that exercises the pipeline of the workspace-mediation test on a reduced pair of real context-conditioned processors, the interoception and vision modules, in a workspace-on arm and a pooled arm only. Both arms SHALL use the same seeds, the same scripted stimulus and identically initialized modules. The harness SHALL be seeded and deterministic, SHALL NOT boot an entity or open a network connection, and SHALL state in its documentation and in every verdict that it is development tooling and does not test the hypothesis.

#### Scenario: Same seed reproduces the run
- **WHEN** the harness runs twice with the same seed and stimulus
- **THEN** both runs produce the same per-report gains, the same effect and the same verdict

#### Scenario: No network
- **WHEN** the harness runs with outbound socket connections made to fail
- **THEN** it completes and produces a verdict

### Requirement: Development harness measures information gain
The harness SHALL read each processor's per-report broadcast information gain, the reduction in its prediction error with the held context relative to the null context of Appendix A.8, in units of its running mean error, as the module publishes it. For each arm, `IG_j` SHALL be the mean gain of processor `j` over its reports that have a defined gain and fall after the initial learning period, undefined when there is none, and the headline `IG` SHALL be the mean of `IG_j` over the two processors, undefined when either is. The run contrast `dIG` SHALL be the workspace-on headline minus the pooled headline. The harness SHALL NOT measure or render the language organ's output.

#### Scenario: Gain defined on the coupled battery
- **WHEN** the harness runs the coupled battery past its initial learning period
- **THEN** `IG_j` is defined for the interoception and vision modules in both arms and `dIG` is defined

#### Scenario: Headline undefined when a processor has no included report
- **WHEN** one processor has no included report in an arm
- **THEN** that arm's headline is undefined

### Requirement: Pooled arm of the development harness
In the pooled arm every candidate of a tick SHALL enter the context, weighted by its reported intensity, with no scoring, selection, access threshold or inhibition. In the workspace-on arm the coalition SHALL be selected by the workspace as built, and the context SHALL be formed from the members whose scores reach the access threshold.

#### Scenario: Pooled snapshot adopts every candidate
- **WHEN** a pooled snapshot of a tick's candidates is delivered to a processor's broadcast context
- **THEN** every candidate is adopted as a context member with its own intensity

### Requirement: Development harness verdict
The harness SHALL classify a run as WIN when `dIG` is at least the minimum effect, NEGATIVE when it is at most the negative of the minimum effect, and NULL otherwise. A run SHALL be NOT EXERCISED when the workspace-on arm never had more candidates than its capacity on a tick, when it had no accessed broadcast, or when `dIG` is undefined; such a run SHALL be reported with the shared outcome NOT EXERCISED and its reason. The verdict SHALL NOT be scored from the language organ.

#### Scenario: Competition never operates
- **WHEN** the workspace-on arm's candidates never exceed its capacity
- **THEN** the run is flagged NOT EXERCISED rather than reported as a clean NULL

#### Scenario: Every outcome is reachable
- **WHEN** the classifier receives a defined `dIG` above, within, or below the minimum-effect band
- **THEN** it returns WIN, NULL and NEGATIVE respectively

### Requirement: Suite aggregation of the development harness
The offline suite SHALL run the harness over several seeds and apply two one-sided exact sign tests to the per-seed `dIG`: the WIN test on `dIG - min_effect` and the NEGATIVE test on `-min_effect - dIG`, dropping exact zeros. The suite SHALL report WIN when the WIN test's p-value is at most alpha, NEGATIVE when the NEGATIVE test's p-value is at most alpha, NOT EXERCISED when no seed was exercised, and NULL otherwise. The WIN test's p-value SHALL enter the suite's Holm family.

#### Scenario: Five positive contrasts at alpha equal to the p-value
- **WHEN** five seeds each give `dIG` above the minimum effect and alpha equals 1/32
- **THEN** the suite reports a WIN

#### Scenario: Five positive contrasts with alpha below the p-value
- **WHEN** five seeds each give `dIG` above the minimum effect and alpha is 0.03
- **THEN** the suite does not report a WIN

#### Scenario: Five positive contrasts below alpha
- **WHEN** five seeds each give `dIG` above the minimum effect and alpha is 0.04
- **THEN** the suite reports a WIN that names the harness as development tooling
