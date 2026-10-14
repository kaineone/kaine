# sleep Specification

## Purpose
The sleep module holds KAINE's sleep and consolidation. This capability defines the five-phase sleep pipeline and its fixed order, non-interruptible sleep, bounded rest deferral, the voice-alignment trainer and its capability-loss veto, lifecycle events and their canonical types, the default configuration, a sleep schedule that survives preservation, and rate-limited rest requests from the action selection module.

## Requirements

### Requirement: Five-phase sleep pipeline runs in fixed order
The sleep module SHALL expose `async enter_sleep()` that runs five phases in
the documented order: memory consolidation, belief revision,
affective reset, temporal recalibration, voice alignment. Each
phase SHALL return a `PhaseResult` carrying `phase` name, `success`
bool, `elapsed_ms`, and `error` (None on success). A failure in any
one phase SHALL be logged and SHALL NOT prevent later phases from
running.

#### Scenario: All five phases ran in order
- **WHEN** `Sleep.enter_sleep()` is awaited against fake
  collaborators
- **THEN** the published `sleep.sleep.completed` event's
  `phases` payload lists exactly the five phase names in the
  documented order

#### Scenario: One phase failing does not stop the others
- **WHEN** the episodic memory module's consolidation phase raises during
  `enter_sleep()`
- **THEN** all four subsequent phases still execute and the
  completion event records `success == False` for memory
  consolidation but `success == True` for the others (assuming they
  succeeded)

### Requirement: Sleep is non-interruptible once begun
The sleep module SHALL acquire an internal lock at the start of
`enter_sleep()` and SHALL not release it until every phase has
finished. A second concurrent call to `enter_sleep()` while one is
already in progress SHALL be rejected with a
`SleepBusyError` rather than starting a second pipeline.

#### Scenario: Concurrent sleep call rejected
- **WHEN** `Sleep.enter_sleep()` is awaited and a second concurrent
  task awaits `Sleep.enter_sleep()` before the first completes
- **THEN** the second call raises `SleepBusyError`

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

### Requirement: Sleep publishes lifecycle events
The sleep module SHALL publish `sleep.sleep.started` at the start of
`enter_sleep()` and `sleep.sleep.completed` at the end. The
completion event payload SHALL contain `total_elapsed_ms`, `phases`
(a list of `PhaseResult` dicts), and `voice_alignment` (a dict
summarizing the training result with the documented keys).

#### Scenario: Started and completed published
- **WHEN** `enter_sleep()` completes
- **THEN** exactly one `sleep.sleep.started` and one
  `sleep.sleep.completed` event appear on `sleep.out`

### Requirement: Default Sleep config and disabled-by-default
The repository SHALL ship a `[sleep]` block in `config/kaine.toml`
with default values for `interval_seconds`,
`max_deferral_seconds`, `per_defer_seconds`,
`planning_step_burst`, `phase_timeout_s`, and a nested
`[sleep.voice_alignment]` table with `intent_log_path`,
`max_samples`, `lora_rank`, `learning_rate`, `dpo_beta`,
`capability_loss_threshold`, `adapter_output_dir`, `model_id`.
`[modules].sleep = false` SHALL keep first boot from
auto-registering the sleep module.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[sleep]` section and a nested
  `[sleep.voice_alignment]` section with the documented keys, and
  `[modules].sleep == false`

### Requirement: Lifecycle-event consumers use the canonical published types

Consumers of the sleep module's sleep lifecycle events SHALL filter on the canonical
published types — `sleep.sleep.started` and `sleep.sleep.completed` — and not
on any other variant. In particular the sleep-snapshot observer, the
voice-tracking observer, and the conversation sleep-state surface SHALL react to
`sleep.sleep.started` / `sleep.sleep.completed`, so they receive the events
the sleep module actually emits.

#### Scenario: Sleep snapshot observer records on the canonical events

- **WHEN** a `sleep.sleep.started` then a `sleep.sleep.completed` event are
  published on `sleep.out`
- **THEN** the sleep-snapshot observer captures the before/after pair

#### Scenario: Voice-tracking observer logs on sleep completion

- **WHEN** a `sleep.sleep.completed` event is published
- **THEN** the voice-tracking observer processes it

#### Scenario: Conversation sleep badge follows the canonical events

- **WHEN** `sleep.sleep.started` then `sleep.sleep.completed` are observed
- **THEN** the conversation sleep state becomes sleeping, then awake

### Requirement: The sleep schedule survives preservation
The sleep module SHALL save its rest schedule as the time remaining until the original and the effective due times, and SHALL restore it against the current process's clock, so a revived entity's next sleep falls where its preserved schedule placed it. Time spent preserved SHALL NOT count toward the next sleep. An overdue schedule SHALL stay overdue after a restore. A snapshot without a saved schedule SHALL start a fresh interval and log that it did; non-finite or inconsistent values SHALL be refused.

#### Scenario: The schedule round-trips across a long gap
- **WHEN** the sleep module has 600 s left until sleep, is preserved, and is revived after a long gap in a new process
- **THEN** its next sleep is due 600 s after the revive

#### Scenario: An old snapshot starts fresh
- **WHEN** the sleep module is restored from a snapshot with no saved schedule
- **THEN** its next sleep is one configured interval away and a log line says the schedule started fresh

### Requirement: Rate-limited rest requests from Action selection

The sleep module SHALL honour an `intent.rest` on `action_selection.out` as a sleep trigger through the same exclusion guards as its fatigue and regulation triggers, only when at least `[sleep].requested_rest_min_interval_s` of entity time (default 1800) has passed since the previous sleep ended. It SHALL publish a content-free `sleep.rest_request` event stating whether the request was accepted and, if not, why (`too_soon`, `busy`). A requested sleep SHALL be an ordinary sleep: non-interruptible and subject to bounded deferral. An operator freeze stops the cycle, so no broadcast and hence no new rest intent occurs while frozen. After a boot or restart the interval SHALL be measured from the boot time, so a restart cannot bypass it.

#### Scenario: A rest request after the interval starts a sleep
- **WHEN** an `intent.rest` arrives after the minimum interval, with no sleep running
- **THEN** the sleep module publishes `sleep.rest_request` with `accepted: true`, and a sleep starts with trigger `requested`

#### Scenario: A rest request too soon is refused
- **WHEN** an `intent.rest` arrives before the minimum interval has passed since the last sleep
- **THEN** no sleep starts, and the sleep module publishes `sleep.rest_request` with `accepted: false`, `reason: "too_soon"`

### Requirement: The rest interval Sleep enforces is the configured one
The composition root SHALL pass `[sleep].requested_rest_min_interval_s` to the sleep module, so the interval the sleep module uses for its own `too_soon` decision is the same value the action selection module's rest proposals use. A value that is not a number greater than 0 SHALL be a configuration error at boot.

#### Scenario: A non-default interval is honoured
- **WHEN** `[sleep].requested_rest_min_interval_s = 600` and a rest request arrives 900 s of entity time after the previous sleep ended
- **THEN** the sleep module accepts it, where the 1800 s default would have refused it as `too_soon`

#### Scenario: An invalid interval refuses boot
- **WHEN** `[sleep].requested_rest_min_interval_s = 0`
- **THEN** building the sleep module raises a configuration error naming the key
