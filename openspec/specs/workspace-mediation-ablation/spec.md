# workspace-mediation-ablation Specification

## Purpose
A two-arm ablation that runs the cycle twice with identical seeds, stimuli and modules, differing only in whether the language organ is conditioned by the competitive workspace or by a flat fan-in of the same outputs, and reports a verdict that can come out against the workspace.

## Requirements

### Requirement: The suite's mediation verdict uses the paper's significance inequality
The offline suite SHALL call the workspace-mediation result significant when the sign-test p-value is at most the suite's alpha (p <= alpha), the rule of paper Appendix A.8, and the Holm correction SHALL reject when an adjusted value is at most alpha, the non-strict rule of Holm (1979). One inequality serves both decisions in the report.

#### Scenario: A p-value equal to alpha is significant
- **WHEN** the per-seed contrasts give a WIN sign-test p-value equal to alpha exactly
- **THEN** the suite reports a WIN for the mediation experiment

#### Scenario: A p-value above alpha is not significant
- **WHEN** the WIN sign-test p-value is above alpha and the NEGATIVE one is too
- **THEN** the suite does not report a WIN or a NEGATIVE for the mediation experiment

### Requirement: Offline development run of the workspace-mediation test
The system SHALL provide an offline development run that exercises the pipeline of the workspace-mediation test on a reduced pair of real context-conditioned processors, the interoception and vision modules, in a workspace-on arm and a pooled arm only. Both arms SHALL use the same seeds, the same scripted stimulus and identically initialized modules. The run SHALL be seeded and deterministic, SHALL NOT boot an entity or open a network connection, and SHALL state in its documentation and in every verdict that it is development tooling and does not test the hypothesis.

#### Scenario: Same seed reproduces the run
- **WHEN** the run executes twice with the same seed and stimulus
- **THEN** both runs produce the same per-report gains, the same effect and the same verdict

#### Scenario: No network
- **WHEN** the run executes with outbound socket connections made to fail
- **THEN** it completes and produces a verdict

### Requirement: Offline development run measures information gain
The run SHALL read each processor's per-report broadcast information gain, the reduction in its prediction error with the held context relative to the null context of Appendix A.8, in units of its running mean error, as the module publishes it. For each arm, `IG_j` SHALL be the mean gain of processor `j` over its reports that have a defined gain and fall after the initial learning period, undefined when there is none, and the headline `IG` SHALL be the mean of `IG_j` over the two processors, undefined when either is. The run contrast `dIG` SHALL be the workspace-on headline minus the pooled headline. The harness SHALL NOT measure or render the language organ's output.

#### Scenario: Gain defined on the coupled battery
- **WHEN** the run executes the coupled battery past its initial learning period
- **THEN** `IG_j` is defined for the interoception and vision modules in both arms and `dIG` is defined

#### Scenario: Headline undefined when a processor has no included report
- **WHEN** one processor has no included report in an arm
- **THEN** that arm's headline is undefined

### Requirement: Pooled arm of the offline development run
In the pooled arm every candidate of a tick SHALL enter the context, weighted by its reported intensity, with no scoring, selection, access threshold or inhibition. In the workspace-on arm the coalition SHALL be selected by the workspace as built, and the context SHALL be formed from the members whose scores reach the access threshold.

#### Scenario: Pooled snapshot adopts every candidate
- **WHEN** a pooled snapshot of a tick's candidates is delivered to a processor's broadcast context
- **THEN** every candidate is adopted as a context member with its own intensity

### Requirement: Offline development run verdict
The offline development run SHALL classify itself as WIN when `dIG` is at least the minimum effect, NEGATIVE when it is at most the negative of the minimum effect, and NULL otherwise. A run SHALL be NOT EXERCISED when the workspace-on arm never had more candidates than its capacity on a tick, when it had no accessed broadcast, or when `dIG` is undefined; such a run SHALL be reported with the shared outcome NOT EXERCISED and its reason. The verdict SHALL NOT be scored from the language organ.

#### Scenario: Competition never operates
- **WHEN** the workspace-on arm's candidates never exceed its capacity
- **THEN** the run is flagged NOT EXERCISED rather than reported as a clean NULL

#### Scenario: Every outcome is reachable
- **WHEN** the classifier receives a defined `dIG` above, within, or below the minimum-effect band
- **THEN** it returns WIN, NULL and NEGATIVE respectively

### Requirement: Suite aggregation of the offline development run
The offline suite SHALL execute the offline development run over several seeds and apply two one-sided exact sign tests to the per-seed `dIG`: the WIN test on `dIG - min_effect` and the NEGATIVE test on `-min_effect - dIG`, dropping exact zeros. The suite SHALL report WIN when the WIN test's p-value is at most alpha, NEGATIVE when the NEGATIVE test's p-value is at most alpha, NOT EXERCISED when no seed was exercised, and NULL otherwise. The WIN test's p-value SHALL enter the suite's Holm family.

#### Scenario: Five positive contrasts at alpha equal to the p-value
- **WHEN** five seeds each give `dIG` above the minimum effect and alpha equals 1/32
- **THEN** the suite reports a WIN

#### Scenario: Five positive contrasts with alpha below the p-value
- **WHEN** five seeds each give `dIG` above the minimum effect and alpha is 0.03
- **THEN** the suite does not report a WIN

#### Scenario: Five positive contrasts below alpha
- **WHEN** five seeds each give `dIG` above the minimum effect and alpha is 0.04
- **THEN** the suite reports a WIN that names the run as development tooling

### Requirement: NOT EXERCISED is the run's own outcome
The offline development run SHALL report a run that is not exercised (the workspace-on
arm never had more candidates than its capacity on a tick, had no accessed broadcast,
or left `dIG` undefined) with the shared outcome NOT_EXERCISED and its reason, not as
a NULL. The suite SHALL apply its two sign tests only to the `dIG` of seeds that were
exercised, SHALL report NOT_EXERCISED when no seed was exercised, and SHALL record
how many seeds were and were not exercised.

#### Scenario: A run without competition is NOT EXERCISED
- **WHEN** the workspace-on arm's candidates never exceed its capacity
- **THEN** the run's verdict outcome is NOT_EXERCISED and its detail gives the reason

#### Scenario: An unexercised seed is not evidence
- **WHEN** a seed is not exercised but its `dIG` is defined
- **THEN** that `dIG` does not enter either sign test

#### Scenario: No exercised seed
- **WHEN** no seed of a suite run is exercised
- **THEN** the suite verdict is NOT_EXERCISED and carries no p-value
