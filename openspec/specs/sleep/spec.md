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

### Requirement: The awake floor reports a missing volume once per change
The awake floor SHALL log a missing watched volume once, and again only after the volume's presence changes. It SHALL go on skipping a missing volume as before.

#### Scenario: A sink that never exists
- **WHEN** a configured sink directory stays missing across many floor checks
- **THEN** the floor logs one warning for it

### Requirement: The sleep index survives a restart
The sleep module SHALL carry its sleep index, the count that tags `sleep.sleep.started` and `sleep.ignition_audit` and names the intent-log corpus files, in its `serialize()` state as `sleep_index`, and SHALL restore it from that state and from the `sleep_count` of `state/lifecycle/stage.json` at `initialize()`, keeping the larger of the restored values and its current count. A `sleep_index` that is not a non-negative integer SHALL be ignored with a warning. A missing or unreadable stage file SHALL leave the count unchanged and SHALL NOT stop the module from starting.

#### Scenario: The next sleep continues the count from the stage file
- **WHEN** the stage file records `sleep_count` 4 and the sleep module starts with no checkpoint
- **THEN** the next sleep's `sleep.sleep.started` event carries `sleep_index` 5

#### Scenario: The larger record wins
- **WHEN** the resume checkpoint holds `sleep_index` 6 and the stage file records `sleep_count` 4, in either restore order
- **THEN** the sleep index is 6

#### Scenario: A malformed checkpoint value is ignored
- **WHEN** the restored state holds `sleep_index` -1, true, "3" or 2.5
- **THEN** the sleep index keeps its current value and a warning is logged

### Requirement: A developmental rest lasts developmental_rest_s
On an `affect.rest_request` with reason `stimulus_spent`, the sleep module SHALL start a sleep with trigger `developmental_rest` under the same guards as the other event-driven triggers. That sleep SHALL run its phases and then stay asleep until `[sleep].developmental_rest_s` (default 1,260 s, Table A1 Delta_rest) of entity time has passed since it began, and SHALL then end with the affective reset. A cancel during the hold SHALL still run the affective reset. Its `sleep.sleep.started` event SHALL carry `trigger` `developmental_rest`, and its `sleep.sleep.completed` summary SHALL carry `trigger` and `rest_seconds`. Every other sleep SHALL end with its phases as before, and its events SHALL be unchanged. `developmental_rest_s` SHALL be a finite number greater than 0.

#### Scenario: The rest holds
- **WHEN** a developmental rest begins and its phases finish after 10 s
- **THEN** the sleep ends with the affective reset 1,260 s of entity time after it began

#### Scenario: An ordinary sleep
- **WHEN** a fatigue-triggered sleep runs
- **THEN** it ends when its phases finish and its summary has no `rest_seconds`

### Requirement: Every sleep runs housekeeping last
When `[sleep.housekeeping].enabled` is true, every sleep that reaches the end of its phases SHALL run housekeeping after the voice and corpus work and before the affective reset, and SHALL add its report to the `sleep.sleep.completed` summary under `housekeeping` (paper section 3.5, A.5). Housekeeping SHALL account the bytes `S_disk` of the regular files under the allowed study-record roots (`data/evaluation`, `data/workspace_trajectory`) and of the current process-log backups, and the bus's memory use `S_mem`. While `S_disk` exceeds `disk_budget_bytes`, it SHALL walk those files oldest first, deleting log backups and exporting closed daily study-record files to `archive_dir` (copy, SHA-256 check, rename) before removing the local copy, until `S_disk` is within the budget, nothing is left to reclaim, or `time_allowance_s` has passed. A study record SHALL NOT be deleted unless an archive copy with the same SHA-256 exists; with no archive set, study records SHALL stay. The report's terms SHALL be handed to the housekeeping pressure. The report SHALL carry the pressure `max(0, S_disk/B_disk - 1) + max(0, S_mem/B_mem - 1) + max(0, S/B - 1)`, the last term from the episodic stores' bytes and budget, 0 without them. A failure SHALL be logged and SHALL NOT stop the sleep; an aborted sleep SHALL skip housekeeping.

#### Scenario: Over budget with an archive
- **WHEN** the study records hold three closed daily files of 4 GB each and today's file, the disk budget is 6 GB and an archive directory is set
- **THEN** the two oldest closed files are moved to the archive, today's file stays, and the bytes after are within the budget and the disk term of the pressure is 0

#### Scenario: No archive mounted
- **WHEN** the study records exceed the budget and `archive_dir` is empty
- **THEN** no study record is moved or deleted, the report says no archive is set, and the disk term of the pressure is the excess

### Requirement: Housekeeping acts only inside its allowlist
Housekeeping, in sleep and in the awake floor, SHALL act only on regular files that resolve inside its allowed roots or are current process-log backups outside `state/`. It SHALL refuse with an error any path outside them, any symlink, and any path under `state/`, where the memory stores, world model, self-model, identity, voice adapters and preservations live. The archive directory SHALL NOT lie inside an allowed root or under `state/`, and configuring it there SHALL fail.

#### Scenario: A protected path
- **WHEN** housekeeping is asked to move `state/episodic_memory/store.db`, `state/sleep/adapters/a.safetensors`, `state/self_model/self_model.json` or a symlink inside `data/evaluation` pointing to one of them
- **THEN** it refuses with an error and the file is untouched

### Requirement: The awake floor keeps free space above a reserve
While the entity is awake and housekeeping is enabled, the cycle SHALL check every `floor_period_s` the free space of every volume a study sink writes to and of `state/`, once per filesystem, against `R^hk = max(reserve_bytes, reserve_share x volume size)` (paper A.5). Below `R^hk` it SHALL reclaim regenerable data on that volume, oldest first, never exporting and never deleting an unexported study record, until free space reaches the target `min(2 R^hk, (volume size + R^hk) / 2)`, and SHALL then count the disk's excess over its budget in the pressure until the next sleep, the disk term becoming the larger of the last sleep's term and this measurement so each byte counts once. If free space is still below `R^hk` it SHALL suspend the study record: each study-record sink SHALL write one gap-start marker and drop entries until the floor resumes the record once every volume that caused the suspension is back at its target, then write a gap-end marker with the count dropped. A failure on one volume SHALL NOT stop the other checks or the resume check. Each action SHALL be logged and published on `housekeeping.out` with labels and byte counts only. A floor value outside its range, or a reserve at least the size of a watched volume, SHALL fail boot.

#### Scenario: Reclaim is enough
- **WHEN** a volume falls below its reserve and deleting log backups brings it above `R^hk`
- **THEN** the floor publishes a reclaim action and the study record continues

#### Scenario: The disk stays full
- **WHEN** reclaiming leaves free space below `R^hk`
- **THEN** the study record is suspended with a gap marker, and it resumes with an end marker once free space is back at `2 R^hk`

### Requirement: The archive side follows no links
Before removing a local study record, housekeeping SHALL refuse that file, keeping the local copy, when the archive destination or any path component between the archive root and it is a symlink, when the destination resolves outside the archive, when it is the same file as the source, or when a non-regular file sits at the temporary name. Every archive-side step below the archive root SHALL go through directory descriptors opened without following links, and an archive root that does not exist SHALL be treated as not mounted. It SHALL create the temporary file exclusively without following links, read every digest through a descriptor that does not follow links, re-verify the destination's digest after the rename and before the removal, sync the destination directory, and re-check with `lstat` that every file it removes is a regular file.

#### Scenario: The destination is a link to the source
- **WHEN** the archive destination of a closed study record is a symlink to that record
- **THEN** the export is refused, the local record stays and the pass goes on with the next file

### Requirement: Exports leave no data behind
Housekeeping SHALL export a study record only when the archive (default `/app/archive`) is a mount point on a device other than every root's, and only when the record is dated before yesterday. Without such an archive, boot SHALL log one operator notice with the projected days until the disk budget is reached at the mean daily growth of the last seven complete days. The disk budget SHALL be `disk_budget_share` (default 0.5, strictly between 0 and 1, validated at boot) of the size of the volume holding the study records, the smallest if they span several, unless `disk_budget_bytes` sets it explicitly. It SHALL remove the local copy only when the source's size, modification time and inode, read through the descriptor it was copied from and by path, are unchanged since the copy; otherwise it SHALL repeat the export once and then keep the file. A shorter archive copy that is a prefix of the source SHALL be replaced. A file that vanishes, becomes a link or has more than one hard link SHALL be skipped without stopping the pass. Host memory SHALL count only bus entries acknowledged by every consumer group and older than the restart replay window; with neither in the bus the memory term SHALL be 0 and reported as not measured.

#### Scenario: A late append
- **WHEN** a sink appends to a record after it was copied and before the local copy is removed
- **THEN** the appended bytes end up in the archive copy or stay in the local file

#### Scenario: An unmounted archive
- **WHEN** `/app/archive` is a plain directory, or a mount point on the same device as the study records
- **THEN** no record is exported, the report says the archive is not mounted, and boot logs the projected days until the budget

#### Scenario: The budget follows the volume
- **WHEN** the study records live on a 400 GB volume and `disk_budget_bytes` is not set
- **THEN** the disk budget is 200 GB

### Requirement: The developmental state cycle times sleep in the developmental phase
While the entity is in the developmental phase, the sleep module SHALL start a sleep with trigger `state_cycle` after `T_act` of awake entity time since boot or since the previous rest ended, where `T_act = developmental_rest_s * (1 - s_q) / s_q` with `s_q = developmental_quiescent_share`. That sleep SHALL run its phases and housekeeping and then hold until `developmental_rest_s` of entity time has passed since it began, and SHALL end with the affective reset. In the phase the hourly backstop SHALL start no sleep, and an `interoception.fatigue` crossing SHALL start no sleep. A maintenance request SHALL still start a sleep. After maturation, or with staging disabled, no `state_cycle` sleep SHALL start and the backstop and fatigue SHALL behave as before. The defaults SHALL be `developmental_rest_s = 1410` and `developmental_quiescent_share = 0.32`, and boot SHALL reject a share outside (0, 1).

#### Scenario: The cycle in the developmental phase
- **WHEN** the entity is developing and 2996 s of awake entity time pass after a rest ends
- **THEN** a sleep with trigger `state_cycle` starts and lasts 1410 s of entity time

#### Scenario: Fatigue in the developmental phase
- **WHEN** the entity is developing and `interoception.fatigue` crosses its threshold
- **THEN** no sleep starts

#### Scenario: After maturation
- **WHEN** the entity has matured and an entity hour passes awake
- **THEN** a sleep with trigger `backstop` starts and ends with its phases

### Requirement: The state cycle survives a restart
The sleep module SHALL persist the state cycle's phase and the entity time spent in it, in the resume checkpoint and across an in-process restart alike. After a restart during awake time the next rest SHALL come when the awake time already spent plus the new awake time reaches `T_act`. After a restart during a rest, including a restart of the process, the rest SHALL resume for its remaining time and then end as any rest does. While a rest runs, the checkpoint's sleep `state_cycle` entry SHALL be brought up to date when the rest starts, after every 60 s of rest, at a shutdown during the rest and when the rest ends, so a crash loses at most 60 s of rest and a crash after a rest resumes none.

#### Scenario: A restart during a rest
- **WHEN** the cycle is restarted 600 s into a 1410 s rest
- **THEN** after the restart the entity rests for the remaining 810 s and the next awake period then begins

#### Scenario: A process restart during a rest
- **WHEN** the process is stopped 710 s into a 1410 s rest and a new process starts on the same state tree
- **THEN** the new process resumes the rest for the remaining 700 s and the maturation gate counts the cut rest and its resumption as one sleep cycle

#### Scenario: A crash during a rest
- **WHEN** the process dies 710 s into a rest with no clean shutdown
- **THEN** the new process resumes the rest from the last 60 s mark, losing at most 60 s of rest

#### Scenario: A crash just after a rest
- **WHEN** the process dies after a rest ended and before the next full checkpoint
- **THEN** the new process resumes no rest

### Requirement: Any completed sleep restarts the awake stretch
A completed sleep of any trigger SHALL restart the awake stretch of the state cycle, so that two rests never run back to back. An aborted sleep SHALL NOT restart it. Time the cycle spends frozen SHALL count toward neither the awake stretch nor a rest.

#### Scenario: A maintenance sleep before a rest
- **WHEN** a maintenance sleep completes with 2900 s of the awake stretch spent
- **THEN** the next `state_cycle` rest starts `T_act` of awake time after that sleep ended

### Requirement: The cycle is carried through restarts of the module and of boot
An in-process restart of the sleep module by the supervisor SHALL carry the module's state, the state cycle included, into the rebuilt module. Until boot has wired the development probe, or its explicit absence, the hourly backstop SHALL start no sleep. A resumed rest SHALL log the time remaining, and the maturation gate SHALL count a rest cut by a cancel and resumed as one sleep cycle, while a rest that failed with an error, which does not resume, counts as one.

#### Scenario: A supervisor restart during a rest
- **WHEN** the supervisor rebuilds the sleep module 600 s into a 1410 s rest
- **THEN** the rebuilt module resumes the rest for the remaining 810 s

#### Scenario: A rest cut by a restart and resumed
- **WHEN** a `state_cycle` rest ends aborted with reason `CancelledError` and the resumed rest completes
- **THEN** the maturation gate counts one sleep cycle

#### Scenario: A revive with an overdue scheduler
- **WHEN** the sleep module initializes with an overdue restored scheduler before the probe is wired
- **THEN** no backstop sleep starts until the probe is wired

### Requirement: Fatigue raises no welfare alarm in the phase
While the entity is in the developmental phase the welfare observer SHALL record no unmaintained-fatigue event, because fatigue sets no sleep there. When the phase ends the interoception module SHALL clear its fatigue latch, so fatigue behaves as before maturation.

#### Scenario: A fatigue crossing in the phase
- **WHEN** `interoception.fatigue` crosses during the developmental phase and no maintenance sleep follows
- **THEN** no `unmaintained_fatigue` gray-zone event is raised
