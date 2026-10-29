## MODIFIED Requirements

### Requirement: Sleep-time ignition audit

The sleep module SHALL, unconditionally on every sleep, audit ignition events in the affect workspace that triggered the entity to speak or any other module to act, covering the window since the previous sleep, and SHALL emit the result as a content-free `sleep.ignition_audit` bus event on sleep.out merged into the PhaseResult metadata (riding `sleep.sleep.completed` into the sleep_snapshots JSONL, carrying `sleep_index`).

The audit SHALL classify each realized speech/action/rest into exactly one category:
- **Realized intents:** intents on `action_selection.out` realized via `external_speech`, `internal_speech`, a successful `vocal.synthesized` or `effectors.action`, excluding `realization_failed` and failed synthesis, and requested sleeps started from an `intent.rest`.
- **Categories:**
  - **planning-initiated:** the realizing intent carries `origin: "planning"`. This is checked first.
  - **input-triggered:** the intent's `entry_id` resolves to a coalition member whose source/type is `audition.transcription` or `embodiment.chat`, or such a type was in the winning coalition of the triggering broadcast.
  - **drive-triggered:** `affect.drive` is in the coalition path.
  - **self-initiated:** none of the above.

The audit SHALL link each realization to the intent it realized: through the realization payload's `entry_id` when present, else through the language module's `record_id`, joined to the `intent_entry_id` of the intent-log record with that id. Only a requested sleep, whose `sleep.sleep.started` carries neither, SHALL be linked to the last `intent.rest` of the window. A speech or action realization with no link SHALL count as self-initiated and SHALL add no entry id; the audit SHALL NOT give it the provenance of another intent. If the intent log cannot be read, the audit SHALL run unlinked.

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

#### Scenario: each utterance is linked to its own intent
- **WHEN** two speak intents E1 (coalition with `affect.drive`) and E2 (coalition without one) are realized as `external_speech` events carrying record ids R1 and R2, and the intent log maps R1 to E1 and R2 to E2
- **THEN** the audit reports one drive-triggered realization with entry id E1 and one self-initiated realization with entry id E2, whatever the order of the two realizations

#### Scenario: an unlinked utterance never takes another intent's provenance
- **WHEN** a realization carries no `entry_id` and a `record_id` that the intent log does not hold, and the last speak intent of the window had `affect.drive` in its coalition
- **THEN** the realization counts as self-initiated and no entry id is recorded for it
