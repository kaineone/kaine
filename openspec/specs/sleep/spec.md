# sleep Specification

## Purpose
The sleep module holds KAINE's sleep and consolidation. This capability defines the five-phase sleep pipeline and its fixed order, non-interruptible sleep, bounded rest deferral, the voice-alignment trainer and its capability-loss veto, lifecycle events and their canonical types, the default configuration, a sleep schedule that survives preservation, and rate-limited rest requests from the action selection module.

## Requirements

### Requirement: Five-phase sleep pipeline runs in fixed order
The sleep module SHALL expose `async enter_sleep()` that runs five phases in the order
the paper gives (§3.5): light consolidation, deep consolidation (memory replay
then synaptic downscaling), associative replay, voice alignment, and the
affective reset. The affective reset SHALL be the last phase, so that sleep
ends with it, and `sleep.sleep.completed` SHALL follow it. The affective reset
SHALL run exactly once even when an earlier phase raises or the sleep is
cancelled, and a second cancel SHALL NOT interrupt it. On any exception,
including a cancel, the sleep module SHALL publish an aborted `sleep.sleep.completed`
and re-raise the exception. Each phase SHALL
return a `PhaseResult` carrying `phase` name, `success` bool, `elapsed_ms`, and
`error` (None on success). A failure in any one phase SHALL be logged and SHALL
NOT prevent later phases from running.

#### Scenario: All five phases ran in order
- **WHEN** `Sleep.enter_sleep()` is awaited against fake collaborators
- **THEN** the published `sleep.sleep.completed` event's `phases` payload
  lists `light_consolidation`, `deep_consolidation`, `associative_replay`,
  `voice_alignment`, `affective_reset`, in that order

#### Scenario: One phase failing does not stop the others
- **WHEN** the episodic memory module's consolidation phase raises during `enter_sleep()`
- **THEN** all four subsequent phases still execute and the completion event
  records `success == False` for light consolidation but `success == True` for
  the others (assuming they succeeded)

#### Scenario: A cancelled sleep still ends with the affective reset
- **WHEN** the task running `enter_sleep()` is cancelled during phase 1, during
  phase 2's replay, or during voice alignment
- **THEN** the affective reset runs once, an aborted `sleep.sleep.completed`
  with reason `CancelledError` is published, the replay window is closed, and
  the CancelledError propagates

#### Scenario: A second cancel does not interrupt the reset
- **WHEN** a second cancel arrives while the final affective reset is running
- **THEN** the CancelledError propagates and the reset still completes

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
`max_deferral_seconds`, `per_defer_seconds`, `baseline_salience`,
`alert_salience` and `requested_rest_min_interval_s`, a nested
`[sleep.consolidation]` table, and a nested
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

#### Scenario: The shipped file sets no retired key
- **WHEN** an operator inspects the `[sleep]` section of `config/kaine.toml`
- **THEN** it does not set `planning_step_burst`

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

### Requirement: Sleep pauses the perceptual feed
The sleep module SHALL suspend external perception (desired locus `off` and the shared playlist clock paused under the `sleep` holder) when a sleep starts, whatever modules are active, and SHALL restore the pre-sleep locus and resume the clock when the sleep ends, including when the sleep pipeline fails or is cancelled.

#### Scenario: Sleep without Episodic memory pauses the feed
- **WHEN** a sleep runs on a profile with the episodic memory module off and the pre-sleep locus is `virtual`
- **THEN** the desired locus is `off` while the sleep runs and `virtual` after it ends

#### Scenario: A failed sleep restores perception
- **WHEN** the sleep pipeline raises or is cancelled
- **THEN** the pre-sleep locus is restored and the playlist clock is resumed

### Requirement: Retired Sleep keys are ignored with a warning
The sleep module factory SHALL accept `[sleep].planning_step_burst`, a retired key that
no longer drives anything, SHALL NOT pass it to the sleep module, and SHALL log a warning
that names the key and says it is ignored. Any other key outside the factory's
accepted set SHALL still stop boot.

#### Scenario: An old operator file still boots
- **WHEN** the operator configuration sets `[sleep].planning_step_burst = 200`
- **THEN** the factory builds the sleep module and logs a warning naming
  `[sleep].planning_step_burst`

#### Scenario: A misspelt key still stops boot
- **WHEN** the `[sleep]` section sets a key the factory neither accepts nor
  lists as retired
- **THEN** building the sleep module raises an unknown-key error

### Requirement: Sleep opens World model's scenario window around phases 2 and 3
When the world model module is present, the sleep module SHALL open its scenario window through
`open_scenario_window()` before phase 2, whose replay cues the world model module through
`episodic_memory.replay`, and SHALL close it through `close_scenario_window()` in a
`finally` after phase 3, which cues the world model module directly, so the window is
closed after an exception or a cancel in either phase. A world model module
collaborator without these methods SHALL be cued as before.

#### Scenario: A sleep cues World model through the bus
- **WHEN** a real sleep module, an episodic memory module and a world model module share a bus with their peer
  polls running, the short-term buffer holds traces, and `enter_sleep()` runs
- **THEN** the world model module publishes a `world_model.scenario` seeded from each
  replayed trace, and the scenario window is closed after the sleep

#### Scenario: A cancel in phase 2 closes the window
- **WHEN** the sleep is cancelled during phase 2's replay
- **THEN** the world model module's scenario window is closed

### Requirement: Shutdown settles an in-flight sleep and the held tasks
The sleep module's `shutdown()` SHALL stop its background loops, then cancel a sleep
task still in flight and wait for it, so that the sleep ends with the
affective reset and an aborted `sleep.sleep.completed`, and SHALL then wait
for the tasks it holds in `_shielded_tasks`. Each wait SHALL be bounded, and
a task still pending after it SHALL be logged and left.

#### Scenario: Shutdown during a sleep
- **WHEN** `shutdown()` is called while a triggered sleep is in phase 2
- **THEN** the affective reset runs once, an aborted `sleep.sleep.completed`
  with reason `CancelledError` is published, and no held task is pending

#### Scenario: Shutdown waits for a held reset
- **WHEN** `shutdown()` is called while the final affective reset is running
- **THEN** shutdown returns after the reset completes

#### Scenario: The wait is bounded
- **WHEN** a held task does not finish
- **THEN** shutdown returns after the bound and logs the pending task

### Requirement: Sleep shuts down before the other modules
The cycle's shutdown and the supervisor's halt SHALL shut the sleep module down first and the other
modules after it in registration order, so a sleep still in flight ends while
The episodic memory, affect and world model modules are up.

#### Scenario: The reset runs while Affect is up
- **WHEN** the cycle shuts its modules down during a sleep, with the sleep module
  registered after the affect module
- **THEN** the affective reset runs before the affect module shuts down
