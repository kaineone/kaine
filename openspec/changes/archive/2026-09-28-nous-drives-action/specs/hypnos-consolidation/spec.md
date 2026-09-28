## MODIFIED Requirements

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
