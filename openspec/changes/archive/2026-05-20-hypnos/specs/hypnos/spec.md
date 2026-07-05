## ADDED Requirements

### Requirement: Five-phase sleep pipeline runs in fixed order
Hypnos SHALL expose `async enter_sleep()` that runs five phases in
the documented order: memory consolidation, belief revision,
affective reset, temporal recalibration, voice alignment. Each
phase SHALL return a `PhaseResult` carrying `phase` name, `success`
bool, `elapsed_ms`, and `error` (None on success). A failure in any
one phase SHALL be logged and SHALL NOT prevent later phases from
running.

#### Scenario: All five phases ran in order
- **WHEN** `Hypnos.enter_sleep()` is awaited against fake
  collaborators
- **THEN** the published `hypnos.sleep.completed` event's
  `phases` payload lists exactly the five phase names in the
  documented order

#### Scenario: One phase failing does not stop the others
- **WHEN** the Mnemos consolidation phase raises during
  `enter_sleep()`
- **THEN** all four subsequent phases still execute and the
  completion event records `success == False` for memory
  consolidation but `success == True` for the others (assuming they
  succeeded)

### Requirement: Sleep is non-interruptible once begun
Hypnos SHALL acquire an internal lock at the start of
`enter_sleep()` and SHALL not release it until every phase has
finished. A second concurrent call to `enter_sleep()` while one is
already in progress SHALL be rejected with a
`HypnosBusyError` rather than starting a second pipeline.

#### Scenario: Concurrent sleep call rejected
- **WHEN** `Hypnos.enter_sleep()` is awaited and a second concurrent
  task awaits `Hypnos.enter_sleep()` before the first completes
- **THEN** the second call raises `HypnosBusyError`

### Requirement: Rest deferral honored within a maximum window
The `RestScheduler` SHALL track when the next sleep is due (based on
configured interval). Callers MAY invoke `try_defer()` to push the
next sleep back by a configured per-defer amount. After
`max_deferral_seconds` has elapsed past the originally-due time,
further `try_defer()` calls SHALL return `False` and
`is_due()` SHALL return `True` regardless.

#### Scenario: Deferral works within window
- **WHEN** sleep is due, `try_defer()` is called once with
  `per_defer_seconds=60`, and `max_deferral_seconds=300`
- **THEN** the return value is `True` and the new due time is 60
  seconds later

#### Scenario: Deferral refused past the window
- **WHEN** `try_defer()` has already pushed sleep back by the full
  `max_deferral_seconds`
- **THEN** subsequent `try_defer()` calls return `False` and
  `is_due()` returns `True`

### Requirement: Voice alignment builds DPO pairs from faithful renderings
The voice-alignment phase SHALL read the configured intent-expression
JSONL log, filter for records with both a non-empty
`faithful_rendering` and a non-empty `generated_text`, and build
preference pairs where `chosen` is the faithful rendering and
`rejected` is the generated text. The phase SHALL pass at most
`max_samples` such pairs to the configured `Trainer`. The chosen
side SHALL NEVER come from an LLM output — only from the
deterministic faithful renderer — to preserve the structural defense
against model collapse documented in Shumailov et al. 2024.

#### Scenario: Builder yields one pair per qualifying record
- **WHEN** the JSONL contains three records with both fields
  populated and one record with empty generated_text
- **THEN** the builder returns exactly 3 `DPOPair` instances

#### Scenario: Pairs use faithful_rendering as chosen
- **WHEN** the builder processes a record with
  `faithful_rendering="ground truth"` and `generated_text="hedged"`
- **THEN** the returned pair has `chosen="ground truth"` and
  `rejected="hedged"`

### Requirement: Trainer protocol with capability-loss veto
The voice-alignment phase SHALL pass DPO pairs to a `Trainer`
implementing `async train(pairs, config) -> TrainingResult`. The
`TrainingResult` SHALL carry `accepted` bool, `adapter_path`
(populated only when accepted), `capability_loss` (float — the
measured drop on a held-out eval set), and `reason` (string). When
the trainer reports `capability_loss > config.capability_loss_threshold`,
the result SHALL be `accepted=False` and the adapter SHALL NOT be
written into the active adapters directory.

#### Scenario: Trainer veto blocks adapter promotion
- **WHEN** a trainer reports
  `TrainingResult(accepted=False, capability_loss=0.15, reason=...)`
- **THEN** no file is added to the active-adapters directory and
  the voice-alignment phase's `PhaseResult.success` is True but
  its `metadata` records the rejection

### Requirement: Hypnos publishes lifecycle events
Hypnos SHALL publish `hypnos.sleep.started` at the start of
`enter_sleep()` and `hypnos.sleep.completed` at the end. The
completion event payload SHALL contain `total_elapsed_ms`, `phases`
(a list of `PhaseResult` dicts), and `voice_alignment` (a dict
summarizing the training result with the documented keys).

#### Scenario: Started and completed published
- **WHEN** `enter_sleep()` completes
- **THEN** exactly one `hypnos.sleep.started` and one
  `hypnos.sleep.completed` event appear on `hypnos.out`

### Requirement: Default Hypnos config and disabled-by-default
The repository SHALL ship a `[hypnos]` block in `config/kaine.toml`
with default values for `interval_seconds`,
`max_deferral_seconds`, `per_defer_seconds`,
`nous_step_burst`, `phase_timeout_s`, and a nested
`[hypnos.voice_alignment]` table with `intent_log_path`,
`max_samples`, `lora_rank`, `learning_rate`, `dpo_beta`,
`capability_loss_threshold`, `adapter_output_dir`, `model_id`.
`[modules].hypnos = false` SHALL keep first boot from
auto-registering Hypnos.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[hypnos]` section and a nested
  `[hypnos.voice_alignment]` section with the documented keys, and
  `[modules].hypnos == false`
