# hypnos-consolidation Specification

## Purpose
Sleep-time memory work: synaptic downscaling, offline replay behind a suspended perceptual locus, and the welfare-gated voice-alignment phase.

## Requirements

### Requirement: NAR belief-revision burst removed
The sleep module SHALL NOT execute a standalone belief-revision step-burst during
maintenance, and SHALL NOT take a planning module collaborator to step. Belief revision
SHALL occur as replayed traces re-enter the workspace and the planning module (pymdp) updates
beliefs on them in the normal cognitive cycle.

#### Scenario: No NAR burst fires during maintenance
- **WHEN** a maintenance cycle runs
- **THEN** no phase named for belief revision runs and the planning module processes replayed
  traces via the standard pymdp update path

#### Scenario: Sleep has no Planning argument
- **WHEN** the sleep module's constructor's parameters are inspected
- **THEN** neither `planning_process` nor `planning_step_burst` is among them

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

The sleep module SHALL, unconditionally on every sleep, audit ignition events in the affect workspace that triggered the entity to speak or any other module to act, covering the window since the previous sleep, and SHALL emit the result as a content-free `sleep.ignition_audit` bus event on sleep.out merged into the PhaseResult metadata (riding `sleep.sleep.completed` into the sleep_snapshots JSONL, carrying `sleep_index`).

The audit SHALL classify each realized speech/action/rest into exactly one category:
- **Realized intents:** intents on `action_selection.out` realized via `external_speech`, `internal_speech`, a successful `vocal.synthesized` or `effectors.action`, excluding `realization_failed` and failed synthesis, and requested sleeps started from an `intent.rest`.
- **Categories:**
  - **planning-initiated:** the realizing intent carries `origin: "planning"`. This is checked first.
  - **input-triggered:** the intent's `entry_id` resolves to a coalition member whose source/type is `audition.transcription` or `embodiment.chat`, or such a type was in the winning coalition of the triggering broadcast.
  - **drive-triggered:** `affect.drive` is in the coalition path.
  - **self-initiated:** none of the above.

The audit SHALL count the planning module's proposals realized, declined and forwarded from `action_selection.proposal_outcome` events. A `forwarded` rest outcome SHALL count only as forwarded, never as declined, because the sleep module decides it. It SHALL also count separately, as unrealizable and never among executed actions, any `intent.*` event published on `planning.out`. The planning module itself publishes none, so this is a guard counter that should read zero.

The audit payload SHALL contain only counts, entry_ids, event types, salience values, and sleep_index; it SHALL NOT contain text, transcripts, or latent vectors.

#### Scenario: realized speak classified self-initiated
- **WHEN** an `intent.speak` on `action_selection.out` with `entry_id` E and no `origin` is realized (`external_speech` or a successful `vocal.synthesized`), and the coalition member resolved via E has source/type `SelfInitiatedReportPolicy`-reported surprise (no external-input type, no `affect.drive`)
- **THEN** the audit classifies it as self-initiated, and its entry_id appears in the self-initiated list for that sleep

#### Scenario: input-triggered count zero under first configuration
- **WHEN** a sleep completes under the first configuration (conversation surface off, transcription off, embodiment module off)
- **THEN** the audit reports `input_triggered_count == 0` for the window, proving the invariant every sleep

#### Scenario: drive-triggered classification
- **WHEN** a realized speech/action's triggering broadcast coalition path includes `affect.drive` and its intent carries no `origin`
- **THEN** it is classified drive-triggered, not self-initiated, not input-triggered

#### Scenario: planning-initiated classification
- **WHEN** a realized intent carries `origin: "planning"`
- **THEN** it is classified planning-initiated, whatever else is in its coalition

#### Scenario: unrealizable planning intents counted separately
- **WHEN** any `intent.*` event is published on `planning.out` during the window
- **THEN** the audit reports its count as a distinct unrealizable figure, and does not count it among executed actions

#### Scenario: planning proposals counted
- **WHEN** `action_selection.proposal_outcome` events are published during the window
- **THEN** the audit reports the counts of realized, declined and forwarded the planning module's proposals

#### Scenario: audit content-free
- **WHEN** the audit payload is emitted (bus event and PhaseResult metadata)
- **THEN** it contains only counts, entry_ids, event types, salience values, and sleep_index, with no text, transcripts, or latents

#### Scenario: audit runs every sleep and rides sleep.completed
- **WHEN** any sleep runs
- **THEN** `sleep.ignition_audit` is emitted on sleep.out with sleep_index, and the audit is merged into PhaseResult metadata so it persists via `sleep.sleep.completed` into the sleep_snapshots JSONL

### Requirement: Phase-3 associative replay links related traces
When `[sleep.consolidation].associative_replay` is true, phase 2 SHALL downscale without pruning, and phase 3 SHALL call the episodic memory module's `associate()` and then its `prune()`, the latter also when `associate()` fails. Phase 3 SHALL publish one `sleep.association` event per co-replayed pair carrying only the pair's two point ids (`a`, `b`) and its new weight (`weight`). Phase 3 SHALL NOT cue the world model module. When the flag is false, phase 3 SHALL be a successful no-op and phase 2 SHALL call `downscale` exactly as before, which prunes.

#### Scenario: Phase 3 off leaves phase 2 unchanged
- **WHEN** a sleep runs with `associative_replay = false`
- **THEN** phase 2 calls `downscale(protect=...)` with no other argument and phase 3 reports that the flag is not enabled

#### Scenario: Phase 3 on links and then prunes
- **WHEN** a sleep runs with `associative_replay = true`
- **THEN** phase 2 calls `downscale(protect=..., prune=False)`, phase 3 calls `associate()` then `prune()`, and one `sleep.association` event with `a`, `b` and `weight` and no text is published per reported pair

#### Scenario: Pruning runs when association fails
- **WHEN** `associate()` raises during phase 3
- **THEN** `prune()` is still called and phase 3 reports failure
