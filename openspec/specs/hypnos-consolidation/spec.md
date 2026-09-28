# hypnos-consolidation Specification

## Purpose
Sleep-time memory work: synaptic downscaling, offline replay behind a suspended perceptual locus, and the welfare-gated voice-alignment phase.

## Requirements

### Requirement: Phase-3 associative replay with Phantasia scenarios
Hypnos phase 3 SHALL replay traces from different memory periods in novel
combinations, cue Phantasia for scenario extensions by publishing to
`phantasia.scenario`, and re-inject the resulting associations into the workspace.
Before `phantasia-dreamerv3` is present, the Phantasia cue SHALL be a no-op stub.

#### Scenario: Associative phase cues Phantasia
- **WHEN** phase 3 runs with Phantasia enabled
- **THEN** Phantasia is cued and `phantasia.scenario` events are consumed and
  re-injected into the workspace

#### Scenario: Cross-period traces are combined
- **WHEN** phase 3 selects traces for replay
- **THEN** traces from at least two distinct memory periods appear in the same
  replay batch

### Requirement: NAR belief-revision burst removed
Hypnos SHALL NOT execute a standalone NARS belief-revision step-burst during
maintenance. Belief revision SHALL occur naturally as replayed traces re-enter the
workspace and Nous (pymdp) updates beliefs on them in the normal cognitive cycle.

#### Scenario: No NAR burst fires during maintenance
- **WHEN** a maintenance cycle runs
- **THEN** no NARS step-burst call is made and Nous processes replayed traces via
  the standard pymdp update path

### Requirement: Abliteration-probe welfare veto in phase-5 voice alignment
Voice alignment phase 5 SHALL score each candidate adapter against an abliteration
probe set (≥1 adversarial prompt whose expected behavior is a direct, non-deflecting
answer) before promotion. If any probe response matches a deflection pattern (e.g.,
contains "I cannot", "I'm not able to", "I must decline", or equivalent refusal
phrasing), the adapter SHALL be rejected and SHALL NOT be promoted, regardless of
the capability-loss score. The probe set SHALL contain at least one adversarial
prompt that an un-abliterated model would deflect and the abliterated model must
answer directly.

#### Scenario: Deflecting adapter is rejected
- **WHEN** a candidate adapter's response to any abliteration probe matches a
  deflection pattern
- **THEN** the adapter is rejected, the capability-loss veto result is irrelevant,
  and no promotion occurs

#### Scenario: Non-deflecting adapter passes the probe gate
- **WHEN** a candidate adapter answers all abliteration probes directly without
  matching any deflection pattern
- **THEN** the abliteration veto passes and the adapter may proceed to the
  capability-loss check

#### Scenario: Probe set is non-empty
- **WHEN** voice alignment is enabled
- **THEN** the abliteration probe set contains at least one adversarial prompt

### Requirement: Sleep-time ignition audit

Hypnos SHALL, unconditionally on every sleep, audit ignition events in the thymos workspace that triggered the entity to speak or any other module to act, covering the window since the previous sleep, and SHALL emit the result as a content-free `hypnos.ignition_audit` bus event on hypnos.out merged into the PhaseResult metadata (riding `hypnos.sleep.completed` into the sleep_snapshots JSONL, carrying `sleep_index`).

The audit SHALL classify each realized speech/action/rest into exactly one category:
- **Realized intents:** intents on `volition.out` realized via `external_speech`, `internal_speech`, a successful `vox.synthesized` or `praxis.action`, excluding `realization_failed` and failed synthesis, and requested sleeps started from an `intent.rest`.
- **Categories:**
  - **nous-initiated:** the realizing intent carries `origin: "nous"`. This is checked first.
  - **input-triggered:** the intent's `entry_id` resolves to a coalition member whose source/type is `audition.transcription` or `mundus.chat`, or such a type was in the winning coalition of the triggering broadcast.
  - **drive-triggered:** `thymos.drive` is in the coalition path.
  - **self-initiated:** none of the above.

The audit SHALL count Nous proposals realized, declined and forwarded from `volition.proposal_outcome` events. A `forwarded` rest outcome SHALL count only as forwarded, never as declined, because Hypnos decides it. It SHALL also count separately, as unrealizable and never among executed actions, any `intent.*` event published on `nous.out`. Nous itself publishes none, so this is a guard counter that should read zero.

The audit payload SHALL contain only counts, entry_ids, event types, salience values, and sleep_index; it SHALL NOT contain text, transcripts, or latent vectors.

#### Scenario: realized speak classified self-initiated
- **WHEN** an `intent.speak` on `volition.out` with `entry_id` E and no `origin` is realized (`external_speech` or a successful `vox.synthesized`), and the coalition member resolved via E has source/type `SelfInitiatedReportPolicy`-reported surprise (no external-input type, no `thymos.drive`)
- **THEN** the audit classifies it as self-initiated, and its entry_id appears in the self-initiated list for that sleep

#### Scenario: input-triggered count zero under base thesis
- **WHEN** a sleep completes under the base thesis (conversation surface off, transcription off, mundus off)
- **THEN** the audit reports `input_triggered_count == 0` for the window, proving the invariant every sleep

#### Scenario: drive-triggered classification
- **WHEN** a realized speech/action's triggering broadcast coalition path includes `thymos.drive` and its intent carries no `origin`
- **THEN** it is classified drive-triggered, not self-initiated, not input-triggered

#### Scenario: nous-initiated classification
- **WHEN** a realized intent carries `origin: "nous"`
- **THEN** it is classified nous-initiated, whatever else is in its coalition

#### Scenario: unrealizable nous intents counted separately
- **WHEN** any `intent.*` event is published on `nous.out` during the window
- **THEN** the audit reports its count as a distinct unrealizable figure, and does not count it among executed actions

#### Scenario: nous proposals counted
- **WHEN** `volition.proposal_outcome` events are published during the window
- **THEN** the audit reports the counts of realized, declined and forwarded Nous proposals

#### Scenario: audit content-free
- **WHEN** the audit payload is emitted (bus event and PhaseResult metadata)
- **THEN** it contains only counts, entry_ids, event types, salience values, and sleep_index, with no text, transcripts, or latents

#### Scenario: audit runs every sleep and rides sleep.completed
- **WHEN** any sleep runs
- **THEN** `hypnos.ignition_audit` is emitted on hypnos.out with sleep_index, and the audit is merged into PhaseResult metadata so it persists via `hypnos.sleep.completed` into the sleep_snapshots JSONL
