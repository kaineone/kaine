# minimal-run-configuration Specification

## Purpose
This capability provides an opt-in minimal experiment configuration that activates only the interoception, sequence and language modules while leaving the workspace and the action selection module always on, keeps every other built module constructed-but-disabled, and forces workspace competition in the smallest runnable set. It also gives the operator a way to inject text stimuli.

## Requirements

### Requirement: Minimal experiment configuration

The system SHALL provide an explicitly-labeled, opt-in experiment configuration that
activates only the modules the ablation needs — the interoception, sequence and language modules — while
leaving the always-on workspace and the action selection module's action layer active. All other
built modules SHALL remain constructed-but-disabled; the configuration SHALL NOT remove
or delete any module. The configuration SHALL set `volition.drive_initiative = false`
so the action selection module matches the paper's described default action policy, and SHALL pin the language module
to greedy decoding.

#### Scenario: Only three modules activate

- **WHEN** the minimal experiment configuration is selected at boot
- **THEN** exactly the interoception, sequence and language modules are registered as modules, the workspace and
  the action selection module run as cycle scaffolding, and every other module is left disabled but still
  present in the codebase

#### Scenario: No work is lost

- **WHEN** the minimal configuration is later switched off
- **THEN** any previously-built module can be reactivated by flipping its `[modules]`
  toggle, with no code restored or rebuilt

#### Scenario: Action selection matches the paper's default policy

- **WHEN** the minimal configuration is active
- **THEN** `volition.drive_initiative` is false, so no drive-initiated intents are
  emitted and the action selection module forms a speak intent only from a user utterance

### Requirement: Workspace capacity forces competition in the minimal set

The minimal experiment configuration SHALL set the workspace `top_k` capacity low
enough that competitive selection genuinely excludes candidates on the minimal set
(which has only two predictive modules plus injected utterances). The shipped default
`top_k = 5` exceeds the minimal set's typical candidate count, so with it selection
never excludes and the ablation would test broadcast mediation and gating but not
competition. The overlay SHALL lower `top_k` (e.g. to 1 or 2) so the workspace-on arm
actually competes, and the choice SHALL be documented alongside the ablation.

#### Scenario: Minimal overlay lowers top_k

- **WHEN** the minimal experiment configuration is active
- **THEN** the workspace `top_k` is set below the minimal set's typical per-tick
  candidate count, so competitive selection excludes candidates rather than admitting
  all of them

### Requirement: Minimal build boots without disabled modules

The minimal configuration SHALL boot and run the cognitive cycle without any hard
dependency on disabled modules (the episodic memory, self-model, affect, perceptual locus, audition modules, and the
rest). Cross-module wiring SHALL degrade cleanly when a module is absent.

#### Scenario: Clean boot on three modules

- **WHEN** the cycle boots with only the interoception, sequence and language modules enabled and the
  operator-present and organ boot gates satisfied
- **THEN** the cycle initializes, the workspace selects, the action selection module gates, and no disabled-
  module dependency raises an error

### Requirement: Operator text-stimulus injection

The system SHALL provide a headless path to inject a single seeded user utterance into
a minimal (Audition-absent) build and to capture the entity's resulting external
speech. The injected stimulus SHALL reach the cycle on a stream the cycle actually
reads, carry the source/type of a user utterance so the action selection module forms a speak intent, and
the resulting output SHALL be observable on `lingua.external`.

#### Scenario: Single stimulus produces capturable output

- **WHEN** the operator injects one seeded user-utterance stimulus into a running
  minimal build
- **THEN** the action selection module forms a speak intent, the language module generates a response, and the response
  is readable from `lingua.external`

#### Scenario: Injection works without the Audition module

- **WHEN** the minimal build has no Audition module registered
- **THEN** the injection path still delivers the utterance to the cycle without
  requiring Audition to be enabled
