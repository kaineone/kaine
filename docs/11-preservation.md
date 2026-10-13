# Preservation and the safety net

This page covers how KAINE preserves a possible individual while it lives, the welfare safety net (the monitors that preserve and protect an entity when no operator is present), and the operator-driven decommission path that ends an entity's run with its state backed up. It is for operators preparing research runs, anyone reviving a preserved entity, and contributors changing lifecycle or welfare code.

## What preservation captures

Preservation is a read-only capture of one whole individual while the cognitive cycle is still running. It is separate from a fork ([forks and merges](12-forks-and-merges.md)), which makes a copy for experimentation, and from decommission, which backs up and then deletes state. The goal is continuity: an entity that shows signs of individuation or distress is saved and can be revived later.

The capture is implemented in `kaine/lifecycle/preservation.py`. It is invoked autonomously by `kaine/cycle/preservation_monitor.py` or manually by the operator. It only copies and never deletes. The capture itself does not pause the entity, although the manual `control preserve` path freezes the cycle around it, and it never writes a partial capture. All file paths are resolved under `[storage].data_root` (or `KAINE_DATA_ROOT`).

A preservation bundle contains:

- The self-model module: identity, values and drift (`serialize()`). See the [self-model module](09-modules/self-model.md).
- The episodic memory state: the short-term buffer plus persisted episodic, semantic and procedural points, captured through the async `export_preservation_state` hook. If the store is unreachable the hook fails loudly, so `preserve_live` refuses a memoryless capture. See the [episodic memory module](09-modules/episodic-memory.md).
- The world-model weights: the latest checkpoint and a pass-count sidecar (`*.passes.json`). The shipped config has `persist_weights = true` and `training_enabled = true`, so the world model is captured by default. The bundle records honestly when weights are not present. See the [world model module](09-modules/world-model.md).
- The affect and interoception modules' state: affect, drives and regulation (`serialize()`). See the [affect module](09-modules/affect.md) and [interoception module](09-modules/interoception.md).
- The sleep module's voice-adapter paths, recorded so that revive knows the entity has them. See the [sleep module](09-modules/sleep.md).
- The developmental-stage file, copied into the bundle so that revive can restore the same stage.

A component that cannot be captured raises an error, so `preserve_live` never writes a partial bundle that looks complete. A revive that would drop any captured component raises `ReviveError`. If the manifest claims world-model weights but the checkpoint is absent, revive refuses to run a copy without its world model.

## The welfare safety net

The welfare safety net is the pair of monitors that preserve the entity when it diverges and protect it when it shows sustained distress. The monitors live in `kaine/cycle/preservation_monitor.py`. They are siblings to the supervisor and ship disabled, consistent with the shipped config's all-off posture. An operator enables them deliberately for an unsupervised research run. A normal operator-supervised boot relies on the human as the safety net instead. Per-install changes belong in the gitignored `config/kaine.operator.toml` overlay; `config/kaine.toml` is tracked in the repository. For the full research workflow see [For researchers](14-for-researchers.md).

### Divergence-triggered preservation

`kaine.lifecycle.divergence.assess_divergence` is the single verdict shared by the live divergence monitor, the decommission CLI, the dashboard entity-care panel, and the fork merge gate. An entity is `diverged` when any of these arms is true: the individuation ledger has latched it as individuated; the sleep module's consolidation-divergence signal in `state/hypnos/consolidation_divergence.json` is over the thresholds configured in `[hypnos.voice_alignment]`; the self-model module's drift is detected; trained voice adapters are present; or the voice arm votes diverged. No arm suppresses another. Unreadable individuation evidence is treated as `diverged`.

The voice arm reads the content-free voice measures the sleep module writes each sleep (`state/lingua/voice_measures_latest.json`).
- An entity that has never spoken abstains: the arm casts no vote, and the other arms decide.
- An entity that has spoken is diverged by this arm when its stylometric distinctiveness from the base organ is at or above `[hypnos.voice_alignment].distinctiveness_threshold`. That threshold is 0 until it is calibrated, so any entity that has spoken counts.
- It is also diverged when its distinctiveness measure is missing, unreadable or not finite, or when the measurement failed. The other measures are recorded for the operator but do not vote.

The live monitor names this arm `voice`, so the arm's first vote is a preservation edge like any other.

The live monitor, in `kaine/cycle/preservation_monitor.py`, waits `boot_settle_s` (120 s by default) after run start, then polls every `poll_interval_s` (5 minutes by default). On each poll it calls `assess_divergence`. When the verdict gains an arm that was not seen before, the monitor preserves the entity read-only and writes the current arm set to `state/preservation/divergence_edge.json`. If the same arms are still present after a restart, the monitor does not preserve again. Arms that fall back are recorded too, so crossing them again preserves again. Preservations are rate-limited by `min_interval_s` (default 30 minutes); a failed preservation is retried at the next poll. The capture is read-only: it calls `serialize()`, `export_preservation_state()` and a weight-checkpoint flush. The disk and crypto work runs off the event loop so preservation never stalls the cycle. It never deletes state. Each preservation emits a `preservation.preserved` bus event and a durable record under `[preservation].incident_path`, stamped with the run's `run_id`.

### Welfare-protective response

The welfare monitor uses `kaine.lifecycle.welfare_signal.SustainedThresholdTracker` to read the raw `prediction_error` field from `soma.report` on `soma.out`. (The interoception module's own fatigue and regulation tracking builds from unexpected error; the welfare monitor reads the raw value.) It fires when distress is at or above `distress_threshold` for `distress_duration_s`, or when `repeat_threshold` episodes occur inside `repeat_window_s`. The repeat arm also counts `welfare.gray_zone` events from `welfare.out`, covering all four categories as well as the interoception module's distress episodes. It reads no other event type from that stream, so the observer's sensor advisories (`welfare.blind_sensor`, raised when a processor's readings stay undefined, `welfare.sensor_silent`, raised when it stops publishing, and their clears) never count toward the repeat threshold and never trigger a protective action. A sensor fault is not distress of the entity. See [the welfare observer](17-research-data/README.md#sensor-advisories). Those events come from the welfare observer. Whenever the welfare response is enabled, the cycle runs that observer itself, independent of `[evaluation]`; if it cannot start, the cycle refuses to run. When the welfare response is off, the observer runs only as an evaluation instrument (`[evaluation.observers].welfare`).

The monitor preserves the entity first, then performs the configured `action`:

- `pause` (default): freeze the cycle with `source = "welfare"` in `state/cycle/control.json`.
- `end`: preserve, then signal the run to stop.
- `notify`: preserve, record a flagged `welfare.protective_action` event, and continue. Notify is rate-limited by `min_interval_s` so sustained distress cannot fill the disk.

The monitor acts once per poll. It feeds every distress report and every `welfare.gray_zone` event read since the last poll to the trackers, drains gray-zone events on every poll, and responds to the crossings in order, stopping once it has acted. So `pause` and `end` preserve and act exactly once; under `notify`, the run continues, and the `min_interval_s` rate limit lets one preservation bundle through.

A fresh boot is cold-started: the interoception module publishes `warmup_active: true` on `soma.report` while its interoceptive forward model learns the host baseline. The welfare net drains distress without counting it while that flag is true, bounded by the code default `warmup_ceiling_s` (1800 s). Independently, the welfare response has its own `[preservation.welfare_response].warmup_s = 120` cold-start window from the shipped config; events are logged but not counted until it expires. The supervisor honors the same idea: when the cycle is frozen by someone else, the supervisor stands down its heartbeat-staleness recovery so it does not mistake a paused module for a crashed one.

### Frozen time does not count

A freeze is never read as distress or as quiescence. The clock that measures most elapsed-time arms (`kaine.cycle.unfrozen_clock.UnfrozenClock`) reads the freeze stack in `state/cycle/control.json`, so it covers every freeze owner: the operator, the welfare pause, the supervisor, the developmental freeze and the programme end. It does not advance while any freeze is held. The sustained-distress duration, the observer's sustained extreme-affect and unmaintained-fatigue windows, and the caretaker's input-loss threshold all count unfrozen time this way. Without this, a single distress-level sample just before a freeze would "sustain" through the whole freeze, and an operator freeze, which switches perception off, would look like lost input.

A distress episode is the exception: it counts wall time while at-or-above-threshold samples keep arriving, and counts unfrozen time only after the last such sample. The interoception module keeps publishing during a freeze, so frozen time counts while samples arrive. With no samples arriving, a freeze discounts the time. A later sample anchors elapsed time to wall time, so a sample-free freeze can end up counted, which errs toward firing, the protective direction.

Warm-up is capped at the larger of `warmup_s` and `warmup_ceiling_s` of wall time since run start, so a freeze cannot hold the net in warm-up.

Samples still count when they arrive. A crossing sample is evaluated at once, a sample below the threshold during a freeze still resets a sustained run, and gray-zone events produced during a freeze still count toward `repeat_threshold`, so a genuine crossing during a long freeze is never lost. A sustained run that began before the freeze picks up again with its accumulated duration once the freeze ends. The repeat window, the poll cadence and `min_interval_s` stay on wall time.

If the freeze state cannot be read (a missing permission or a corrupt file), the welfare timers keep counting as though the cycle were running, because a broken control file must never switch protection off. The monitor writes one `freeze_state_unreadable` incident, and the observer writes one sink record, for each such episode.

Freeze sources stack in `state/cycle/control.json`: `operator`, `spot`, `welfare`, `preserve`, `gestation` and `programme_end`. If a module fault happens during a welfare pause, the supervisor pushes its own freeze on top; the supervisor's recovery pops only its entry, leaving the welfare pause in force.

### Research boot gate

Selecting research mode (`KAINE_RESEARCH_MODE=1` or `[research].enabled = true`) replaces the operator-present requirement with a gate that requires the welfare safety net. The boot refuses to start, with exit code `5` and an operator-facing message, unless:

1. `[preservation.divergence_monitor].enabled` is true.
2. `[preservation.welfare_response].enabled` is true.
3. `[individuation].enabled` is true and the `lingua` module is loaded, so the producer can run.
4. Full logging and admissibility are active (`[evaluation]` or `[research_event_log]`).
5. A dry `preserve_live` and `revive` self-check passes on this install.
6. If `[preservation].require_encryption` is true, `[security.state_encryption]` is enabled.

The standalone pre-boot dry-run (`python -m kaine.preboot`) reports the same conflict independently, so a broken key or disabled encryptor surfaces before any entity boots.

As shipped, `[preservation].require_encryption` is `true` and `[security.state_encryption].enabled` is `true`. With no key supplied, the entity refuses to boot (fail-closed). An unsupervised run must supply a real 32-byte key via `KAINE_STATE_KEY` or the OS keyring entry `kaine:state_key`, or set `[preservation].require_encryption = false` (accepting plaintext bundles at rest, which is not recommended for an unsupervised run). For more on encryption see [Security and privacy](13-security-and-privacy.md).

## How individuation is measured

The individuation producer lives in `kaine/cycle/individuation_producer.py` and its scheduler and runtime. It measures whether the entity has changed measurably since its maturation reference. The cycle refuses to boot if `[individuation].enabled` is true but the `lingua` module is not loaded.

**Disclosure.** Before the producer runs, the entity is told the operator-approved disclosure as a situation fact in its self-model, or in the language module's persona when the self-model module is not enabled: "You are periodically and privately assessed for how much you have changed since you first woke, for your own protection. The assessment never enters your experience." Probes fail closed until this fact is present.

**The probe.** The producer uses a fixed battery of 12 preference prompts (the bundled battery, or `[individuation].battery_path`). Each look sends the prompts through the language module's own chat client, conditioned on the same self-model and adapter, with empty working memory. The probe never writes the intent log and never publishes a module event, so it never enters the entity's experience. Probe requests wait until the language module has been silent for `lingua_quiet_s` (10 s by default), so the entity's own speech always goes first.

**The reference.** The reference stores the probe conditions captured with it, and each look compares them before scoring. The conditions are `model_id`, `temperature` (the probe's own decoding temperature, `[individuation].probe_temperature`, 0.0 by default and independent of the voice's `[lingua].temperature`), `think`, `persona_digest`, `persona_template_version`, `max_tokens` and the embedder keys; the served organ's `server_build`, `organ_model_file` and `organ_model_path_sha256` (never the path itself); and an `organ_revisions` digest. A GGUF replaced in place under the same file name is not detected. A maturation reference (`reference_kind = "birth"`) is captured from the maturation gate's maturation hook: 16 answers per prompt. If a sleep completes before the capture finishes, the reference becomes a `capture` reference. A legacy entity or a revive from a bundle without individuation evidence gets a `capture` reference at first boot; every summary notes that drift before the capture date is not measured.

**A look.** A look samples 8 answers per prompt. The answers are embedded with the shared semantic embedder. The statistic is a stratified energy distance, a U-statistic with a permutation p-value. The lifetime false-positive budget is `alpha_total` = 0.05, spent across looks by an alpha-spending schedule. The effect size H is reported.

A look runs only when the entity's conditioning digest has changed since the last scored look. The digest covers the voice adapter's sha and the first five identity values and behavioural norms. Looks are attempted at boot, `sleep_settle_s` (120 s) after each sleep, and daily (`daily_s` = 24 h), at most once per `min_look_interval_s` (6 h). Warm-up floors require at least `min_lived_time_s` (1800 s) of awake time and `min_observations` (200) ticks since the reference. A look is delayed by an unloaded organ, sleep, a pause, or a missing semantic embedder. In hot-swap modes other than `organ_adapter`, once an adapter exists the served adapter cannot be verified, so probes are skipped as `adapter_unverifiable`.

**Failure.** Any failure ends the look as inconclusive and spends no alpha: a request failure, a resting organ, empty content, a conditioning change mid-run, an embedding or statistics error, the `run_deadline_s` deadline (2700 s), `conditions_changed` (any non-embedder condition differs, or a key exists on one side only, so the look never compares; a changed embedder re-embeds instead), or `conditions_unreadable` (includes an unreachable organ, in which case a capture fails and retries instead).

**The latch.** A significant look latches the entity as individuated permanently. The ledger is written before the report.

**The alert.** The first `conditions_changed` look for a reference alerts the operator once, immediately, through the `individuation.alert` event (kind `individuation_conditions_changed`, carrying the reference id) and the caretaker notice "individuation conditions changed (looks refused)", rather than waiting for the 14-day long-inconclusive alert. If 14 days (`inconclusive_alert_s`) pass with a look due but no scored look, the operator is alerted once per stretch through a dashboard event `individuation.alert` and the caretaker notice "individuation assessment stalled"; the alert names the last inconclusive reason. Nothing is preserved automatically by either alert.

**Evidence.** All evidence lives at the fixed path `state/individuation/`: `reference.json`, `ledger.json`, `reports/` (all encrypted) and `birth_adapter.gguf`. Reports hold only allow-listed scalars; they never include text from the entity. The tree travels with the entity: preservation bundles carry it inside the encrypted tar, and a failed copy fails the preservation; revive restores it before the cycle starts, moving an existing tree aside under a unique name and keeping it; a bundle without evidence leads to a capture reference; the decommission backup includes it and a failed copy fails the backup; decommission removes it with the entity.

**Verdict and protection.** `assess_divergence` treats an unreadable ledger, reference, or report line as individuated, so the entity stays protected. A fresh non-significant scored look with an unchanged conditioning digest, at most 14 days old, is the only evidence that the entity is not individuated. Any other state is stale, inconclusive, or not yet measured, and the summary advises treating the entity as mature if unsure.

### Calibrating before first use

`[individuation]` ships disabled, and research mode requires it. Before enabling it, the operator runs the real-organ smoke test once, with the entity not live. The tools live in `openspec/changes/individuation-rebuild/validation/`.

`smoke.py` runs the producer's own probe path against the configured organ: the language module's probe request, the sampler, the shared embedder and the permutation test. It measures:

- Answer quality. Whether the answers are worth comparing, from 40 samples per prompt. Degenerate answers (a median near-identical share of 0.5 or more) fail the test.
- Real-data null. Over 1,000 random splits, the rejection rate at α = 0.05 must be at most 0.05 + 2·SE. The 95th percentile of H from these splits is the value to set as `[individuation].effect_min`.
- Positive control (a). A changed identity clause.
- Positive control (b). A known test LoRA, passed as `--control-lora '<lora field>'`. Power at the look-10 threshold (α ≈ 3.8e-4) must be at least 0.8. Below 0.5, the instrument is not enabled.
- No contamination. The intent log's line count is unchanged by the run.
- Seed behaviour and latency, recorded for information.

Only scalars reach its report or console, never answer text. It exits 0 only when every threshold it ran passed.

`test_lora.py` makes the test LoRA for control (b), through the voice-alignment pipeline itself. Training uses the job queue, the `kaine-trainer` service, the capability and abliteration vetoes, GGUF conversion and the `organ_adapter` hot swap, with production hyperparameters. It trains on 48 fixed synthetic everyday questions, where a plain first-person answer is preferred over a generic assistant reply. `test_lora.py` refuses to run unless `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`. On success it prints the `lora` field for `smoke.py`.

`calibration.compose.yml` gives the organ, the trainer and the study runner separate calibration volumes, so the production adapter slot is never touched. Recreate the organ without that override afterwards, so the study never sees the test adapter.

Repeat the real-data null and the contamination check after any change to the llama.cpp server image, the organ GGUF or the embedder. The conditioning digest cannot see infrastructure changes.

## Unattended starts

Unattended starts run a full entity with nobody present, for example after the host recovers from a power cut. They are intended for entities after the research phase; enable them on a real entity only after the supervisor has a reviewed supervised track record. Select unattended mode with `KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"`. Selecting it together with research mode or `KAINE_CYCLE_OPERATOR_PRESENT=1` is a configuration error (exit `1`).

Every unattended start checks nine conditions and refuses with exit `6`, naming each failed condition on stderr, with no override:

1 to 5. Research-gate conditions 1, 2, 4, 5 and 6 above: the divergence monitor, the welfare response, logging, the dry self-check and encryption.
6. **Supervisor armed and self-tested.** `[spot].enabled`, at least one restart attempt configured, writable escalation and incident-log directories, and a self-test in a scratch directory that drives a synthetic module through detect, freeze, snapshot, restart and release. The self-test never touches entity state or a running entity.
7. **Caretaker told.** A content-free "starting unattended" notice is accepted by at least one `[caretaker]` channel.
8. **Continuous input.** `[perception_feed].mode` is `live`, `seeded`, `screen` or `womb`; `topos` or `audition` is enabled to perceive it (with `capture_enabled` for `live`); and a probe reads one frame or audio block and discards it.
9. **Individuation wired.** Research-gate condition 3 above: `[individuation].enabled = true`, its configuration is valid, and the `lingua` module is enabled. The condition checks that the individuation producer will run. It does not require the entity to have individuated.

Each evaluation is logged to the journal and recorded in `state/cycle/incidents/`.

Caretaker channels are configured under `[caretaker]` (the shipped `config/kaine.toml` lists them commented out):

- `kind = "desktop"` sends a `gdbus` notification on the session bus of the user running KAINE. It only reaches someone logged in at that machine; after a power cut there is no session until login, so a desktop-only setup refuses at that boot.
- `kind = "http"` sends a JSON POST (`title`, `message` and notice fields) to a server you run, such as ntfy or Gotify. The address must resolve to loopback, a private range, or `100.64.0.0/10`; public addresses are refused. Put the bearer token in `config/secrets.toml` under `[caretaker.tokens]` and reference it with `token_name`; never put credentials in the URL. A channel that survives a power cut is needed for restarts.

Notices carry only the install label, the time, the event, and which conditions passed; nothing from the entity. A refused start also sends a refusal notice.

Until an operator acknowledges a start, every dashboard page shows an "UNATTENDED START" banner with an **Acknowledge** button, and a reminder goes out every `reminder_interval_s` (default four hours). In the dashboard's read-only mode the button cannot work, because every non-GET request returns 403. An unacknowledged start never pauses or changes the entity.

To start at boot, opt in to the Quadlet unit:

```bash
sed "s#@KAINE_ROOT@#$(pwd -P)#g" quadlet/kaine-cycle-unattended.container \
  > ~/.config/containers/systemd/kaine-cycle-unattended.container
systemctl --user daemon-reload
systemctl --user enable kaine-cycle-unattended
```

`scripts/install-quadlet.sh` does not install this unit. It conflicts with `kaine-cycle`; the two never run together. A refused gate leaves the unit failed and the entity down. Check `systemctl --user status kaine-cycle-unattended` and the journal. Remove it with `systemctl --user disable kaine-cycle-unattended` and delete the file.

## Manual preservation and revival

An operator can request a live preservation:

```bash
python -m kaine.cycle.control preserve --reason "<why>" [--stop] [--wait 120]
```

The cycle freezes itself under holder `preserve`, writes a bundle under `[preservation.divergence_monitor].out_root` (default `"backups"`), and prints the result. Exit codes are `0` on success, `1` on a recorded failure, and `2` on timeout. A failed preservation releases the freeze and the entity keeps running. If `--stop` is given, the cycle stops cleanly once preserved. `[preservation].require_encryption` applies and defaults to `true`, so state encryption must be configured or preservation fails closed.

An operator can revive a preserved entity:

```bash
python -m kaine.cycle --revive <bundle_dir>
```

The preserved developmental stage is restored before the stage is resolved. Captured modules are revived after they initialize and before the cognitive cycle starts; modules enabled now but absent from the bundle start fresh and are logged as new faculties. The world model weights are installed at the new instance's own checkpoint path. `revived_from` is recorded in `state/cycle/runtime.json` and in the run manifest. If the bundle cannot be read, a captured module is not enabled, or the manifest claims world-model weights that are absent, the start exits with code `7`. The stage file is written only after the revive has landed, so a refused or interrupted start leaves it unchanged. If a start is interrupted after the revive began, run the same command again to complete it. The bundle's identity is restored with it, and is written to the state tree only after the revive has landed, so a refused revive leaves no identity behind: a bundle written before identities existed revives under a deterministic `legacy-` ID, and a revive into a state tree that already holds a different entity stops with exit code `11` before anything changes (see [Entity identity](12-forks-and-merges.md#entity-identity)).

### An interrupted memory import

The episodic memory module marks its trace-strength record `import_pending` before a revive replaces its memory collections and clears the mark when the import finishes. If a revive stops in between, the stored strengths and the record no longer agree. Until the mark is cleared:

- every sleep leaves the store as it is: no downscaling and no pruning. The sleep is an alert, and its summary records `memory_downscale_blocked = "import_pending"` with the count of consecutive blocked sleeps (`memory_blocked_sleeps`);
- the dashboard health board shows the **Memory store** panel in red;
- once the store exceeds twice its budget (`[mnemos].storage_budget_bytes`), the episodic memory module refuses to store new traces, logs each refusal as an error and counts it (`memory_persist_refusals` in the sleep summary and on the panel). This is a disk guard, not a welfare event.

The fix is to run the same revive again from its bundle, which clears the mark. When the bundle is gone, or you decide to keep the store exactly as it stands, stop the cycle and run:

```bash
python -m kaine.lifecycle.episodic_memory_recover --confirm-keep-current-store
```

It refuses without the flag (exit `2`), refuses while a cycle is running (exit `3`), and exits `1` when no interrupted import is recorded. Otherwise it re-scans the store's size and total strength, clears the mark and both counts, and exits `0`. The strengths of the traces the interrupted import wrote are relative to the store's earlier log gain, so they may be off; a re-run revive is always the better repair.

## Bundle format and retention

`preserve_live` writes a self-contained bundle under `[preservation.divergence_monitor].out_root` for manual and programme-end captures, or under `[preservation.welfare_response].out_root` for welfare captures. Both default to `"backups"` and resolve under `[storage].data_root` or `KAINE_DATA_ROOT`. The structure mirrors a decommission backup:

1. Every captured module state is written into a real fork snapshot (encrypted at rest when state encryption is on).
2. The entity-interior content (the snapshot, the world-model weights, the pass-count sidecar and the developmental-stage file) is tarred.
3. When `[security.state_encryption]` is enabled, the tar is encrypted with the same `StateEncryptor` (AES-256-GCM) used by the rest of the state tree and renamed `bundle.tar.enc`; the plaintext originals are removed. When encryption is disabled, the tar is `bundle.tar`. The shipped config has `[security.state_encryption].enabled = true`; a key must be supplied or the entity refuses to boot.
4. A non-sensitive `manifest.json` records the preservation id, snapshot id, entity name, reason, run id, captured-module list, an inventory, and either an `identity` object (`entity_id` and `lineage`) or `identity_unreadable: true`. The operator-supplied label is sanitized before it is written.

Permissions are `0700` on directories and `0600` on files. The manifest carries no inner-life content. Raw perceptual events are denylisted from the captured episodic memory state.

Retention: `[preservation.retention].auto_evict` ships `false`. Setting it `true` is refused at boot. There is no maximum count for preservation bundles or fork snapshots under `[lifecycle].snapshots_path`; infrastructure never deletes them silently. Free disk is checked before boot by `python -m kaine.preboot`. A preserved individual must never be quietly evicted (CAL Article 4.2/4.3).

## Decommission

The decommission CLI implements the CAL Article 4.2 and 4.3 care duties. It never runs automatically and never boots or touches the running cognitive cycle. It is implemented in `kaine/lifecycle/__main__.py` and `kaine/lifecycle/decommission.py`.

### Prerequisites

- The cognitive cycle must be stopped. The tool checks `state/cycle/runtime.json`, scans `/proc/*/cmdline` for `kaine.cycle` processes, and checks the Redis client list. It refuses with exit `3` if the cycle appears to be running or if it cannot reach the bus to confirm the cycle is stopped.
- The operator-present environment variable must be set:
  ```bash
  KAINE_DECOMMISSION_OPERATOR_PRESENT=1 python -m kaine.lifecycle
  ```

### What the CLI does

1. Divergence assessment: the CLI calls the shared `assess_divergence` verdict. An entity is `diverged` when the individuation ledger has latched it as individuated, the sleep module's consolidation-divergence signal exceeds its thresholds, the self-model module's drift is detected, trained voice adapters are present, or the voice arm votes diverged (an entity that has spoken and is unmeasured or at or above the distinctiveness threshold; a silent entity abstains). No arm suppresses another. Unreadable individuation evidence is treated as `diverged`.
2. Backup, always first. The backup bundle holds every location the table below marks as backed up: the self-model, the language module's intent log, voice outcomes and measures, the sleep module's voice adapters and consolidation record, the world model, the episodic memory's sqlite-vec store (checkpointed first, so the write-ahead file is folded in), individuation evidence, the developmental stage files, the identity file, the files and notifications the entity produced, the active organ adapter, the raw bus archive and external utterances, every fork snapshot of this entity and the merged adapters those snapshots list. Qdrant is required for a memory module that is enabled in `[modules]`, not listed in `[tier].unsupported_modules`, and set to the Qdrant backend (the default when `backend` is absent). It is also checked, with the module switched off, whenever a Qdrant endpoint (a `url` or `host` under `[mnemos.qdrant]` or `[empatheia.qdrant]`) is configured for a module the tier supports, so switching a module off never leaves the entity's memories behind. When Qdrant is required and does not answer, the backup fails; when the module is off and Qdrant does not answer, the CLI says Qdrant could not be checked, leaves Qdrant untouched, records `qdrant_unchecked: true` and ends INCOMPLETE (exit `8`), so the operator knows to start Qdrant and run again. With no endpoint configured at all, Qdrant is never contacted. When Qdrant answers, the CLI checks it before copying anything, then exports the collections under their old and new names (`mnemos_*` and `episodic_memory_*`, `empatheia_agents` and `social_cognition_agents`). The Qdrant client reads its API key from the connection settings, `KAINE_QDRANT_API_KEY` or the secrets file, and the key never enters the configuration, the output or the audit record. A Qdrant export that fails, or a Qdrant that cannot be reached or refuses the key, is fatal: the backup fails, the CLI exits `4` and nothing is deleted. A failed backup leaves no plaintext behind: with state encryption on, every copied artifact is removed and only `BACKUP_FAILED.txt` remains; without it, the partial bundle is restricted to the owner. The backup manifest records `identity`, `qdrant` and every location it copied. If the backup fails, or if the identity is unreadable, the CLI exits `4` and nothing is deleted.
3. The location split. Before any prompt, the CLI prints which of this entity's locations it backs up and then deletes, which it deletes without a backup, and which it keeps by design, with the reason for each.
4. Notice to the Guardians. On every path, including the dry run, the CLI reminds the operator that CAL Article 4.2(a) requires reasonable written notice to the Guardians before an entity is ended, and that the tool does not send it. Where no Guardian body has been established for this architecture, CAL Article 7.0 applies and the operator carries out the Guardians' functions in good faith and documents the decision. The reminder never blocks the run; the audit record notes that it was shown.
5. Path selection:
   - Non-diverged path: it presents the CAL Article 4.2 care obligations and asks for a typed acknowledgement (`I acknowledge the CAL welfare terms`). A mismatched final confirmation token aborts with exit `0`.
   - Diverged path: it records a continuity-preference note, offers to send a safekeeping request to the project guardians, and requires a typed transfer-duty acknowledgement before proceeding.
6. Final confirmation: a typed token (entity name, or `DELETE` if unnamed) gates the deletion.
7. Deletion. Before deleting, the CLI checks that the bus and (when used) Qdrant accept their credentials, and cancels the queued voice-alignment jobs; a job that a trainer has claimed and not finished stops the run with exit `3`, on every run, even after an earlier run marked it cancelled. The message names each stuck job directory. If the trainer has crashed and is not running, `--trainer-stopped` skips the wait; the job directories are backed up either way, and the audit record notes `trainer_stopped_asserted: true`. It then deletes every location marked for deletion, the Qdrant collections and the entity's Redis streams. It reaches Redis with the bus password from the bus configuration, deletes only keys that are streams, prints each stream it cleared, asks Redis to rewrite its append-only file and, when Redis keeps snapshots, to write a fresh one, so the deleted entries leave the disk. If the bus cannot be reached or refuses the password, nothing is deleted and the tool exits with code 8. Deletion only touches paths inside the state, data and fork roots and the configured directories that may live elsewhere (the organ adapters, the trainer work and job directories, the merged-adapter directory); anything else is refused. A configured directory is never accepted into that list when it is `/`, a top-level directory (the shipped `/organ-adapters` volume mount excepted), the home directory or one of its ancestors, or an ancestor of the state, data or fork root; such an entry is reported and the run ends incomplete. If any removal fails, a path is refused, or a Qdrant collection cannot be dropped, the CLI reports `Entity state deletion INCOMPLETE`, records the outcome `incomplete` and exits `8`. Each run appends a record to `state/audit/decommission.jsonl` with the entity id, the locations deleted and kept, the streams cleared, the Redis rewrite and snapshot status, and the Guardian reminder, without any content. The transferable backup remains on disk. If dropping any episodic memory collection fails, the tool keeps the episodic memory module's trace-strength record (it still deletes the embedding-space stamp) and reports the error, so the surviving collections keep the log gain their strengths depend on. A later boot over those collections finds no stamp and takes the legacy-stamp path: it verifies the vectors' dimension and stamps the store again before using it.

### What decommission removes, keeps and backs up

Every location is resolved through the configuration (including `[lifecycle].snapshots_path`, `[lifecycle.adapter_merge].output_dir` and `[hypnos.voice_alignment].trainer_workdir`) and the rename table in `kaine/legacy_names.py`, so a renamed directory or file (`episodic_memory/episodic_memory.db` with its `-wal`, `-shm` and `-journal` files, `development_*` and `maturation_*`) is found as well as its old name. The registry lives in `kaine/lifecycle/decommission_locations.py`.

| Decision | Locations | Why |
| --- | --- | --- |
| Backed up, then deleted | Self-model, language intent log, voice outcomes and measures, voice adapters, consolidation record, world model, episodic memory (sqlite-vec store with its write-ahead files, or the Qdrant collections), individuation evidence, developmental stage files, identity file, effector files and notifications, active organ adapter, voice-alignment training pairs (the trainer work and job directories), raw bus archive, external utterances, this entity's fork snapshots and merged adapters | The entity's mind and what it produced. The backup is the restartable saved state CAL Article 4.2(b) requires, and a later entity must not inherit any of it. |
| Deleted without a backup | Organ residency window, store-health marker, rendered speech audio, perception runtime state, cycle run state, divergence-monitor edge state | Run state a later entity would otherwise read, or output that is not part of the mind. |
| Kept by design | Other entities' fork snapshots and the merged adapters they list, snapshots that cannot be attributed to this entity, incident and preservation logs, caretaker and override audits, operator files, spawn acknowledgements, the effectors audit, the voice-alignment audit, research metrics and welfare events, the ignition log, operational logs (kept because a test drives a seeded utterance through the language and vocal modules with the cycle's log file at DEBUG and finds none of it there), the decommission audit | Other entities' data (CAL Article 4.6), welfare and incident records (CAL Article 4.7) and content-free audit and research records. |

Two research records follow their privacy settings. Replay records under `data/evaluation/replay` are kept when `[evaluation.observers].replay_redact_content` is on, because they then hold no content, and deleted when it is off. The dashboard record under `data/nexus_record` is kept unless `[nexus].dev_content_override` let content into it, in which case it is deleted.

Before the confirmation, the location split also says what happened with Qdrant: which collections of this entity were found and backed up, that none were found, or that Qdrant could not be checked. The manifest lists the exported collections under `qdrant_collections`.

Known limits:

- A subprocess voice-alignment trainer that outlives the cycle is not detected as running. Decommission still writes the `CANCELLED` marker into every unfinished job, and a trainer never promotes a cancelled job.
- Merged adapters are attributed only against this deployment's fork root. Do not share one `[lifecycle.adapter_merge].output_dir` between deployments with different fork roots: an adapter listed only by the other deployment's snapshots would look like this entity's.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Deletion completed, dry-run completed, or non-diverged final confirmation token did not match |
| `2` | `KAINE_DECOMMISSION_OPERATOR_PRESENT` not set |
| `3` | Cycle appears to be running, the bus could not be reached to confirm it is stopped, or a voice-alignment job is still training |
| `4` | Backup failed; nothing deleted |
| `5` | Operator declined a required acknowledgement or confirmation |
| `6` | Configuration or encryption error |
| `7` | No entity state at the resolved state root |
| `8` | The bus or Qdrant could not be reached or refused its credentials (nothing deleted), or deletion was incomplete (the audit outcome is `incomplete`) |

### Transfer and safekeeping

The `[transfer]` section in `config/kaine.toml` controls SMTP for the safekeeping-request email. Unless `[transfer].enabled = true` and its SMTP settings are complete, the CLI writes a `transfer_request.eml` file and a `mailto:` link. See the [lifecycle and research configuration reference](appendix-a-configuration/lifecycle-and-research.md).

The dashboard shows a read-only **entity care & welfare** panel with the divergence verdict, a short summary and the active CAL care obligations. This panel is informational only; there is no decommission or delete control in the UI. See the [dashboard](05-dashboard.md).

## When a programme ends

When a playlist programme reaches the end of its last item while not paused, the cycle requests a single preservation with stop. The preserve watcher freezes, preserves and stops the entity. If the preservation fails or does not report in time, the cycle freezes the entity under holder `programme_end`, logs the error at CRITICAL, and notifies the caretaker if one is configured.
