# Sleep

The sleep module is the sleep analog: a fatigue-triggered offline period during which the four predictive processors stop adapting their forward models, and at whose end affect and drives return to baseline. This page is the module reference. It covers what starts a sleep, what a sleep does in the first configuration and with the held modules, the events the sleep module publishes, and its configuration. The full pipeline is described in [Sleep and maintenance](../10-sleep/README.md), and the gated training phase in [Voice alignment](../10-sleep/voice-alignment.md).

## Status

The sleep module ships disabled in the default config (`[modules].sleep = false` in `config/kaine.toml`). The `first_configuration` profile enables it, because fatigue-triggered rest and the affective reset are part of the first configuration.

Three parts of the pipeline stay off unless an operator turns them on. Associative replay needs `[sleep.consolidation].associative_replay = true` and the episodic memory module. Voice alignment needs `[sleep.voice_alignment].enabled = true` and the environment variable `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`, and even then it trains nothing, because no validated preference source exists yet (see [Voice alignment](../10-sleep/voice-alignment.md)). Memory consolidation and replay need the episodic memory module.

## What a sleep is

A sleep runs between a `sleep.sleep.started` and a `sleep.sleep.completed` event. The cognitive cycle keeps running throughout. A sleep lock stops a second sleep from starting, and nothing else waits on it. When the sleep starts, `enter_sleep` switches the perceptual locus to `off` and pauses the shared stimulus playlist; when it ends, including after a failure or cancellation, it restores the remembered pre-sleep locus (falling back to `physical`) and resumes the playlist. Sleep time does not count as awake time.

The predictive processors read `sleep.out` and suspend forward-model adaptation for the whole window: the vision, audition (both its acoustic and its tone forward models), interoception and sequence modules. Each keeps predicting and reporting, but none updates its weights until `sleep.sleep.completed` arrives. The interoception module's fatigue decays three times faster while the window is open.

Every sleep ends with phase 5, the affective reset. It calls the affect module's `affective_reset()`, which returns valence, arousal and dominance to baseline, clears the drives (the learning-progress and alert-rate trackers and the intent rate carry on by their own rules), and publishes `affect.state` with `reset: true` (see [the affect module](affect.md#sleep-reset)). When `sleep.sleep.completed` arrives, the interoception module resets its fatigue accumulator and its regulation state. Because every sleep ends this way, arousal cannot drift across a whole run.

### In the first configuration

With the episodic memory module, the world model module and voice alignment off, the consolidation phases do no work:

- Phase 1 calls the oscillator hook, a no-op unless the oscillatory layer is active, and skips consolidation.
- Phase 2 returns at once. The perceptual feed is paused for the whole sleep in any case (see [Sleep](../10-sleep/README.md)).
- Phase 3 is skipped by its flag.
- Phase 4 checks the voice-alignment gates and builds no pairs and trains nothing. The sleep module then rotates the language organ's intent log into the per-sleep corpus and computes the content-free voice measures.
- Phase 5 resets the affect module.

After the phases the sleep module runs the sleep-time intent audit. A base-form sleep is therefore short, and what it does is suspend adaptation, reset affect and drives, and reset the interoception module's fatigue. The consolidation phases begin to work once the episodic memory and world model modules join.

## Triggers

| Trigger | Source | Condition |
|---|---|---|
| Fatigue | `interoception.out`, `interoception.fatigue` | `crossed == true`; ignored in the developmental phase (see [The developmental state cycle](#the-developmental-state-cycle)) |
| Maintenance request | `interoception.out`, `interoception.regulation` | `action == "request_maintenance"` |
| Emotion-regulation request | `affect.out`, `affect.regulation` | `action == "request_maintenance"` (tier 3 of the affect module's emotion regulation) |
| State cycle | The maintenance poll | In the developmental phase, `T_act` of awake entity time since boot or since the previous rest ended (see [The developmental state cycle](#the-developmental-state-cycle)) |
| Interval backstop | `RestScheduler.is_due()` | `interval_seconds` of entity time since the last completed sleep, or since boot (one entity hour by default); starts no sleep in the developmental phase |
| Requested rest | `action_selection.out`, `intent.rest` | At least `requested_rest_min_interval_s` of entity time since the last sleep ended, and no sleep running |

Every sleep records the trigger that started it as `trigger` on `sleep.sleep.started` and on `sleep.sleep.completed`, aborted ones included. The values are `fatigue`, `maintenance_request` (the interoception module's request), `affect_regulation` (emotion regulation's tier 3 request), `state_cycle` (the developmental state cycle), `requested` (an accepted rest request) and `backstop` (the maintenance poll). A direct `enter_sleep()` call without a trigger records null. The summary's `fatigue_triggered` is true only for a sleep whose trigger is `fatigue`. A trigger that arrives while a sleep is starting or running starts nothing and leaves the running sleep's trigger as it was.

The fatigue, maintenance and emotion-regulation triggers share one consumer loop, which runs only when `[sleep.consolidation].fatigue_triggered = true`. A maintenance poll checks `is_due()` regardless. `is_due()` is true once the effective deadline has passed, or once the original deadline plus `max_deferral_seconds` has passed. `try_defer()` pushes the effective deadline back by `per_defer_seconds`, up to that cap; nothing in the running system calls it outside tests.

Rest requests come from the planning module through the action selection module's `PlanningProposalSource` (`origin = "planning"`), so they arise only when the planning module is enabled. The sleep module answers each with a `sleep.rest_request` event at intensity 0.0, so the answer never competes for the workspace.

### The developmental state cycle

(Paper 3.5, Table A1.) In the developmental phase sleep follows the fetal state cycle in place of the hourly backstop. A rest stands for quiescence (state 1F) and awake time for the active states 2F and 4F. Near term the fetus is quiescent about a third of the time, in epochs with a median length of 23.5 minutes at 38 weeks (Nijhuis et al. 1982). The rest lasts `developmental_rest_s` (`Delta_rest`, 1,410 s) and rest fills the share `developmental_quiescent_share` (`s_q`, 0.32) of entity time, so the awake time between rests is `T_act = Delta_rest (1 - s_q) / s_q`, about 2,996 s. The module computes `T_act` once from the two settings.

While the development probe says the entity is developing, the maintenance poll counts awake entity time since boot or since the previous rest ended. Time inside any sleep does not count. When the count reaches `T_act` the poll starts a sleep with trigger `state_cycle`. That sleep runs its phases and then stays asleep until `developmental_rest_s` of entity time has passed since it began; housekeeping then runs, and the sleep ends with the affective reset like every sleep. A cancel or shutdown during the hold still runs the reset, and the aborted completion event then also carries `trigger` and `rest_seconds`. The `sleep.sleep.started` event of a state-cycle rest carries `trigger: "state_cycle"`, `rest_seconds` and `resumed`, and its `sleep.sleep.completed` summary carries `trigger` and `rest_seconds`. During the rest the cycle runs on, the perceptual feed pauses except the developmental stimulus, and forward-model adaptation is suspended, as in every sleep. The rest counts as time asleep for lived time, the development owner and the welfare observer.

In the phase the hourly backstop starts no sleep, and an `interoception.fatigue` crossing starts none either (the consumer reads it and logs it at debug). Sleep homeostasis emerges only in the second postnatal month (Jenni and LeBourgeois 2006), so the cycle and not fatigue times sleep in this phase. A maintenance request from the interoception module or from emotion regulation still starts a sleep, which ends with its phases. A stalled boredom goal is abandoned and starts no rest.

The probe is the one the affect module uses, wired by `_wire_affect_development`. With no probe (staging off), or after maturation, no `state_cycle` sleep starts and the backstop and the fatigue trigger behave as they always did. A probe that raises counts as developing.

The cycle survives a restart. `serialize()` writes `state_cycle`, with the phase (`awake` or `resting`) and the entity time spent in it. After a restart during awake time the next rest comes when the awake time already spent plus the new awake time reaches `T_act`. After a restart during a rest, including a rest cut by shutdown, the module starts a `state_cycle` sleep at once and holds it for the remaining time only; its started event then carries `resumed: true` and `rest_seconds` as the remaining time. The started event of a resumed rest carries the remaining rest length in `rest_seconds`. Any completed sleep (maintenance, emotion regulation or requested) restarts the awake stretch, so two rests never run back to back; an aborted sleep does not. Time frozen by the cycle (a freeze) counts toward neither the awake stretch nor the rest. A snapshot without `state_cycle` starts a fresh cycle at boot. A rest that fails with an error does not resume; the awake stretch starts over. The supervisor carries the module's state through an in-process restart (`carries_state_across_restart`): it serializes the module after shutdown and deserializes it into the rebuilt one. The backstop waits until boot has wired the development probe (or its explicit absence), so a restored overdue scheduler cannot fire it first. The maturation gate counts a resumed rest once: an aborted `state_cycle` completion counts nothing and the resumed completion counts as the sleep cycle. The welfare observer raises no `unmaintained_fatigue` event in the phase, because fatigue sets no sleep there, and the interoception module clears its fatigue latch when the phase ends so a standing crossing is announced again.

## Pipeline

```mermaid
flowchart TD
    S([fatigue crossed\nOR request_maintenance\nOR interval due\nOR accepted intent.rest]) -->|acquire sleep lock| ST[sleep.sleep.started]
    ST --> P1
    P1["Phase 1: light consolidation\n• set_frequency(0.5) on active modules\n• episodic_memory.consolidate_now()"]
    P1 --> P2
    P2["Phase 2: deep consolidation (needs EpisodicMemory)\n• open the replay window; episodic_memory.replay_now(); close it\n• episodic_memory.downscale(protect=replayed traces): downscale, then prune\n  (with phase 3 on: downscale only)"]
    P2 --> P3
    P3["Phase 3: associative replay (flag)\n• episodic_memory.associate(): link related pairs\n• episodic_memory.prune()\n• publish sleep.association per pair"]
    P3 --> P4
    P4["Phase 4: voice alignment\n• gates; no pairs, no training\n• intent-log rotation, voice measures"]
    P4 --> HK["Housekeeping\n• log backups deleted, study records exported\n• pressure P^hk"]
    HK --> P5
    P5["Phase 5: affective reset\n• affect.affective_reset()"]
    P5 --> R[Intent audit]
    R --> E([sleep.sleep.completed])
```

Each phase catches its own errors, and the later phases still run after one fails. The affective reset runs in a `finally` after phases 1 to 4, shielded from a second cancel, so even a sleep that raises or is cancelled ends with it, and an aborted `sleep.sleep.completed` is published on any exception, including a cancel. Phase 3 follows the paper's associative replay (A.10): the episodic memory module co-replays at most five pairs, most similar first, of a trace replayed in phase 2 and one stored in an earlier wake, records each pair as a weighted link, and then prunes. With phase 3 on, phase 2 therefore downscales without pruning, so that pruning follows the co-replays as A.10 orders it; with phase 3 off, phase 2 downscales and prunes as before. Phase 3 publishes one `sleep.association` event per pair, carrying the two point ids and the link weight and no memory content, and prunes even when the co-replay fails. It does not cue the world model module. The order follows the paper (§3.5): replay, then synaptic downscaling, then associative replay, then the voice, and sleep ends with the affective reset. Phase 2 opens the episodic memory module's replay window itself, immediately before it replays, and closes it afterwards, so replay never depends on the episodic memory module having seen `sleep.sleep.started` on the bus. When the world model module is present, the sleep module also opens its scenario window before phase 2, whose replay cues the world model module through `episodic_memory.replay`, and closes it in a `finally` after phase 3. On shutdown, the sleep module stops its loops, cancels a sleep still in flight and waits for it, so the sleep ends with the affective reset and an aborted `sleep.sleep.completed`, then waits for the reset and publish tasks it holds; each wait is bounded at 5 s. The cycle's shutdown and Supervisor's halt shut the sleep module down before the other modules, so the sleep ends while the episodic memory, affect and world model modules are still up. The phase functions are in `kaine/modules/sleep/phases.py`; phase 4 is driven from `kaine/modules/sleep/module.py`.

### Housekeeping

(Paper 3.5 and A.5.) Regenerable or spent data is what no module reads again and the entity's continuation does not need. In this build that is two things: the rotated backups `<file>.1` to `<file>.N` of the process log, written when the cycle runs with `--log-file` (the live file is never touched), and local study-record copies whose archive copy matches by SHA-256. Every sleep that reaches the end of phase 4 runs housekeeping last, before the affective reset.

Its roots are the directories the study sinks write to, taken from the configuration: `[evaluation.paths].evaluation_logs` and `trajectory_dir`, and the `log_dir` or `archive_dir` of the research event log, the external utterances, the dashboard record and the raw bus archive. A sink directory under `state/` is watched by the floor and suspended with the others, but never reclaimed. Housekeeping counts the bytes of every regular file under the roots, plus the log backups. While they exceed the disk budget it walks them oldest first by modification time. The budget is `disk_budget_share` (0.5) of the size of the volume holding the study records, the smallest one if they span several, so the pressure rises only when the disk is really getting full; `disk_budget_bytes` overrides it with a fixed size. A log backup is deleted. A closed daily study-record file (`<name>-YYYY-MM-DD.jsonl` dated before yesterday, UTC, because a sink can still append a late batch to yesterday's file just after midnight) is exported to `archive_dir`, keeping its layout under the root's name. The copy is written to a temporary name, synced and checked by SHA-256 against the bytes read from the source, then renamed. Just before the local copy is removed, the source is checked again through the descriptor it was copied from: if its size, modification time or inode changed, the export is repeated once and otherwise skipped, so nothing appended late is lost. An archive copy that is a shorter prefix of the source is a stale partial export and is replaced; one that matches is kept and the local copy removed; any other archive copy is kept and the file skipped. A file with more than one hard link is skipped, since it could share an inode with protected data.

The archive side follows no links. A destination, or any directory between the archive root and it, that is a symlink, a destination that resolves outside the archive or is the same file as the source, and a planted `.part` name are refused for that file, and the local copy stays. Every step below the archive root runs through directory descriptors opened without following links, so no checked component is traversed by name again. The temporary file is created exclusively without following links and removed on any failure, every digest is read through a descriptor that does not follow links, the destination is checked again after the rename (and its directory synced), and every removal re-checks with `lstat` that it is a regular file. A file that vanishes or turns into a link during the pass is skipped and the pass goes on.

The archive is detected, not configured. `archive_dir` defaults to `/app/archive` and counts only when it is a mount point on another device than every study-record root; then study records are exported without any config edit. Otherwise no study record is exported and boot logs one operator notice with the projected time until the disk budget is reached, from the mean daily growth of the study records over the last seven complete days. With no archive the study records stay on the host, as the paper requires of unexported records, and the pressure rises only as the disk fills, since the budget is a share of the volume.

To give the entity an archive, bind a drive at `/app/archive` in the `kaine-cycle` container with a compose overlay, for example `compose/kaine.archive.yml`:

```yaml
services:
  kaine-cycle:
    volumes:
      - /mnt/archive-drive/kaine:/app/archive
```

and add `-f compose/kaine.archive.yml` after `-f compose/kaine.yml` in the command that starts the cycle (for example `docker compose -f compose/kaine.yml -f compose/kaine.archive.yml --profile cycle run --rm kaine-cycle`). The host path must be on another disk (or a network share) than the study-record volumes, or the mount check refuses it; the next sleep exports the oldest closed records.

The pass stops when the bytes are within budget, nothing is left to reclaim, or `time_allowance_s` (`Delta_hk`) has passed. Whatever is left carries over to the next sleep, and so does everything after an aborted sleep, which skips housekeeping. Host memory is not measured: the paper counts there only bus entries acknowledged by every consumer group and older than the restart replay window, and the bus has neither, so the memory term is 0 and the report says `memory_measured: false`. The sleep pass and the awake floor share one lock, so they never act at the same time.

The report goes into `sleep.sleep.completed` under `housekeeping`: bytes before and after, the budgets, the episodic stores' bytes and budget, the files and bytes exported and deleted, why it stopped (`within_budget`, `no_archive`, `no_candidates` or `time`), whether the archive is mounted, the elapsed time, the three terms and the pressure `P^hk = max(0, S_disk/B_disk - 1) + max(0, S_mem/B_mem - 1) + max(0, S/B - 1)`, whose last term is the episodic stores' excess (A.10), 0 without the episodic memory module. It names no files. A failure is logged, reported as `{"failed": true}` and never stops the sleep.

The pressure reaches the entity only through fatigue. A process-wide holder (`kaine.housekeeping_pressure`) takes the terms of each successful report, and the interoception module's fatigue accumulator builds at `nu_act (1 + P^hk)` while awake, so a resource at twice its budget doubles the build-up; there is no ceiling, and asleep the build is unchanged. With no excess the factor is 1 and fatigue is exactly as before.

### Awake floor

(Paper 3.5 and A.5.) The floor runs in the cycle, outside the entity's state, while the sleep module and housekeeping are enabled. Every `floor_period_s` while awake it checks the free space of every volume a study sink writes to and of `state/` (once per filesystem) against `R^hk = max(reserve_bytes, reserve_share x volume size)`. Below `R^hk` it reclaims regenerable data on that volume only, oldest first, until free space reaches the target: log backups and study-record copies whose archive copy matches by SHA-256, never exporting and never removing an unexported study record. The target is `2 R^hk`; where `2 R^hk` does not fit the volume, which the paper does not cover, it is halfway between `R^hk` and the volume size, so the record can always resume. If free space is still below `R^hk` it suspends the study record: every study-record sink (the evaluation and research logs, the broadcast log, the external utterances, the dashboard record, the raw bus archive and the welfare record) writes one `{"record_gap": "start"}` marker and drops what follows. Once every volume that caused the suspension is back at its target, the floor resumes it and each sink writes `{"record_gap": "end", "dropped": n}` before its next record. A volume whose path is missing is skipped; the floor warns once when it first sees the path missing, stays silent while it stays missing, logs an info line when it appears and warns again if it later disappears. A failing volume check is logged and the others, and the resume check, still run; the floor checks again that the entity is awake before each volume. Each action is logged as a warning and published on `housekeeping.out` (`housekeeping.floor`, with the action, the volume label and byte counts, no paths); that stream is not a module stream, so the entity never sees it. After a reclaim the disk's excess over its budget at that moment counts in `P^hk` until the next sleep: the disk term becomes the larger of the last sleep's term and this measurement, since both measure the same bytes and adding them would count those bytes twice.

Bad floor values (`reserve_share` outside (0, 1), a reserve or period not above 0) fail boot, and so does a reserve that is at least the size of a watched volume.

Neither path touches the memory stores, the world model, the self-model and identity, the voice adapters or the preservations. Housekeeping acts only on regular files inside its roots and on the current process-log backups, and refuses a path that resolves elsewhere and anything under `state/`, where all of those live; the archive may not lie inside a root or under `state/`. The research event log keeps `retention_days = 0`: its files leave the host only through the archive.

Not built, because the code holds nothing the paper's definition covers: container logs are kept by the container runtime (capped by the compose logging options), no cache rebuilt on demand lives in the data tree, and the bus uses no consumer groups and has no restart replay window, so no bus entry is ever acknowledged by every group and none is measured or reclaimed. The pressure lives in memory, so after a restart it is 0 until the next sleep or floor action measures it again.

## Outputs

| Stream | Event type | Description | Intensity |
|---|---|---|---|
| `sleep.out` | `sleep.sleep.started` | Start of the pipeline; carries `started_at`, `sleep_index` and `trigger`, the trigger that started this sleep | `baseline_salience` |
| `sleep.out` | `sleep.sleep.completed` | Summary: `phases`, `voice_alignment`, `total_elapsed_ms`, `trigger`, `fatigue_triggered`, `pairs_processed`, `dpo_loss`, the capability scores, `corpus`, `voice_measures` and `ignition_audit`. If the pipeline itself aborts, the payload is `{"aborted": true, "reason": <exception class name>, "trigger": ...}` | `baseline_salience` when every phase succeeded, else `alert_salience` |
| `sleep.out` | `sleep.association` | One phase-3 co-replayed pair: `a` and `b` (point ids) and `weight`, no content | `baseline_salience` |
| `sleep.out` | `sleep.rest_request` | Answer to a rest request: `accepted`, and `reason` of `accepted`, `busy`, `too_soon` or `aborted` | `0.0` |
| `sleep.out` | `sleep.ignition_audit` | Content-free intent audit, every sleep | `baseline_salience` |

The sleep module reports at these fixed levels; its events are not graded by surprise. The interoception module resets fatigue and regulation in response to `sleep.sleep.completed`, and the four processors resume adaptation on it, so an aborted sleep still ends the window.

## Configuration

The full reference is in [Perception feed and sleep](../appendix-a-configuration/perception-and-sleep.md). Intervals run in entity time.

`[sleep]`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `interval_seconds` | float `> 0` | `3600.0` | Interval backstop: longest time between completed sleeps |
| `max_deferral_seconds` | float `>= 0` | `600.0` | Most the backstop can be deferred past its original deadline |
| `per_defer_seconds` | float `> 0` | `60.0` | Deferral added per `try_defer()` |
| `requested_rest_min_interval_s` | float `> 0` | `1800.0` | Minimum time from the end of a sleep before a rest request is accepted |
| `developmental_rest_s` | float `> 0` | `1410.0` | Length of a state-cycle rest in entity seconds (paper Table A1 `Delta_rest`, Nijhuis et al. 1982) |
| `developmental_quiescent_share` | float `(0, 1)` | `0.32` | Share of developmental entity time spent resting (paper Table A1 `s_q`, Nijhuis et al. 1982); sets `T_act = Delta_rest (1 - s_q) / s_q` |
| `baseline_salience` | float `[0, 1]` | `0.5` | Intensity of routine sleep events |
| `alert_salience` | float `[0, 1]` | `0.8` | Intensity of a completed event after a failed phase |

The retired key `planning_step_burst` is accepted and ignored with a warning, so older local configs still boot.

`[sleep.consolidation]`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `fatigue_triggered` | bool | `true` | Run the `interoception.out` consumer; `false` disables both the fatigue and the maintenance-request triggers |
| `replay_window_s` | float | `5.0` | Recorded in phase-2 metadata; replay runs to completion regardless |
| `associative_replay` | bool | `false` | Enable phase 3, associative replay; its parameters are `[episodic_memory.association]` |

`downscale_factor` is refused at boot: phase 2 downscales trace strengths by `[episodic_memory.strength].retention_per_day` instead (paper A.10).

`[sleep.voice_alignment]` is documented in full on the [Voice alignment](../10-sleep/voice-alignment.md#configuration) page.

## Sleep-time intent audit

Every sleep, the sleep module publishes `sleep.ignition_audit` for the window since the previous sleep (or since boot). It classifies each realized intent, an `external_speech`, `internal_speech`, `vocal.synthesized` or `effectors.action` event or a requested `sleep.sleep.started` (never a `realization_failed`), by the coalition that produced it:

| Class | Rule |
|---|---|
| `planning_initiated` | The intent's `origin` is `"planning"`; checked first |
| `input_triggered` | The coalition holds `audition.transcription` or `embodiment.chat` |
| `drive_triggered` | The coalition holds `affect.drive` |
| `self_initiated` | None of the above |

Each realization is linked to the intent it realized. The language module's `external_speech` and `internal_speech` payloads carry the `record_id` of the intent-log record written for that utterance, and that record holds `intent_entry_id`, the `entry_id` of the intent. The audit reads this join from the two newest intent-log files (the corpus file rotated in this sleep, or the newest one if nothing was rotated, and the live log). A payload `entry_id`, where an event carries one, is used directly. A requested `sleep.sleep.started` carries neither, so it is linked to the last `intent.rest` of the window. A speech or action realization with no link counts as `self_initiated` and adds no entry id, so one intent's coalition is never applied to another intent's utterance. If the intent log cannot be read, the audit runs unlinked and logs a warning.

`intent.*` events on `planning.out` are counted separately as unrealizable, since no effector reads that stream, and `action_selection.proposal_outcome` events add realized, declined and forwarded proposal counts. The payload holds counts, entry ids, event types, intensities and `sleep_index`, and no text, transcripts or latent vectors. It is also merged into the `sleep.sleep.completed` summary.

## Sleep index

The sleep index counts the sleeps of the entity's life: it rises by one at the start of each sleep, and `sleep.sleep.started` carries it as `sleep_index`, which the language module records with each utterance. It names the corpus files (`sleep-<UTC time>-<index>.jsonl`) and tags `sleep.ignition_audit`. It survives a restart: the module saves it in its resume-checkpoint state as `sleep_index`, and at start it also reads the cumulative `sleep_count` of `state/lifecycle/stage.json`, keeping the larger value.

Voice adaptation builds no preference pairs and computes no organ-level divergence until a validated preference source exists (paper section 3.5). The phase builds pairs from the intent-log corpus only after its three gates pass (enabled, operator approval, a validated preference source), and no source is validated yet. It publishes no divergence metric and writes no `state/sleep/consolidation_divergence.json`. The pair builder's chosen text (the faithful rendering the organ was given) and rejected text (the organ's reply) always differ, so the metric it used to publish was 1.0 for every entity at every sleep and marked every entity as diverged at its first sleep. A record left by an earlier build is no longer read.

## Key files

| File | Role |
|---|---|
| `kaine/modules/sleep/module.py` | `Sleep`: triggers, pipeline, perception suspension, divergence, phase 4 |
| `kaine/modules/sleep/phases.py` | Phases 1 to 4 |
| `kaine/modules/sleep/scheduler.py` | `RestScheduler`: interval and deferral |
| `kaine/modules/sleep/ignition_audit.py` | Sleep-time intent audit |
| `kaine/modules/sleep/corpus.py` | Intent-log rotation and the corpus ceiling check |
| `kaine/modules/sleep/voice_measures.py` | Content-free voice measures |
| `kaine/modules/sleep/voice_alignment.py` | `VoiceAlignmentConfig`, `DPOPairBuilder`, `FakeTrainer`, the divergence record |
| `kaine/modules/sleep/subprocess_trainer.py` | `SubprocessVoiceTrainer`, used by the `in_process` and `subprocess` backends |
| `kaine/modules/sleep/job_queue_trainer.py` | `JobQueueVoiceTrainer`, the cycle side of the `job_queue` backend |
| `kaine/modules/sleep/trainer_service.py` | The `kaine-trainer` service |
| `kaine/modules/sleep/capability_eval.py` | Capability and abliteration probe evaluators |
| `kaine/modules/sleep/adapter_store.py` | Atomic promotion and retention |
| `kaine/modules/sleep/hot_swap.py` | Hot-swap dispatch |
| `kaine/modules/sleep/organ_adapter.py` | Per-entity adapter activation on the organ server |
| `kaine/modules/sleep/organ_window.py` | Single-GPU unload, train and reload bracket |
| `kaine/modules/sleep/voice_audit.py` | Abliteration-veto audit trail |
| `kaine/boot/factories/sleep.py` | Config parsing, backend and hot-swap validation, trainer selection |

## Enabling and use

1. Set `[modules].sleep = true`, or run the `first_configuration` profile.
2. Enable the interoception module for the fatigue and maintenance triggers and the affect module for the affective reset.
3. For memory consolidation and replay, enable the episodic memory module. For associative replay, also set `[sleep.consolidation].associative_replay = true`.

## Tests

| File | Coverage |
|---|---|
| `tests/test_sleep_phases.py` | Phase functions and `PhaseResult` shape |
| `tests/test_sleep_module.py` | Full pipeline and the completed-event shape |
| `tests/test_sleep_trigger.py` | Fatigue trigger |
| `tests/test_sleep_scheduler.py` | Interval and deferral |
| `tests/test_sleep_rest_requests.py` | `intent.rest` handling |
| `tests/test_sleep_sleep_pause.py` | The perceptual locus module and playlist pause and restore |
| `tests/test_sleep_associative_replay.py` | Phase 3: `associate()` then `prune()`, the content-free `sleep.association` events, and phase 2 unchanged with the flag off |
| `tests/test_sleep_oscillator_hook.py` | Phase-1 oscillator hook |
| `tests/test_sleep_nar_removal.py` | Replay reaching the workspace through the normal cycle |
| `tests/test_sleep_replay_handoff.py` | Phase 2 replaying the traces phase 1 consolidated, with the episodic memory module |
| `tests/test_interoception_sleep_flag.py` | The interoception module's `crossed` flag |
| `tests/test_sleep_suspension_cursor.py` | the vision, audition and sequence modules suspending adaptation during sleep |
| `tests/test_sleep_voice_alignment.py`, `tests/test_sleep_voice_alignment_integration.py` | Pair builder, gates and vetoes |
| `tests/test_sleep_organ_window_bracket.py` | Organ window |
| `tests/test_sleep_world_model_window.py` | the world model module's scenario window around phases 2 and 3, through a real sleep on the bus |
| `tests/test_sleep_shutdown.py` | Shutdown during a sleep and during a held reset; the bounded wait |
| `tests/test_module_shutdown_order.py` | The cycle and Supervisor shut the sleep module down first, so the reset runs while the affect module is up |


## See also

- [Sleep and maintenance](../10-sleep/README.md)
- [Voice alignment](../10-sleep/voice-alignment.md)
- [Interoception](interoception.md), [Affect](affect.md), [Episodic memory](episodic-memory.md), [World model](world-model.md), [Language](language.md)
- [Preservation and the safety net](../11-preservation.md)
- [Perception feed and sleep](../appendix-a-configuration/perception-and-sleep.md)
