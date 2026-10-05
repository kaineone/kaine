# Preservation and the safety net

This page covers how KAINE preserves a possible individual while it lives, the autonomous welfare net that protects an entity during unsupervised research, and the operator-driven decommission path for ending a run safely. It is for operators preparing research runs, anyone reviving a preserved entity, and contributors changing lifecycle or welfare code.

## What preservation captures

Preservation is a read-only capture of one whole individual while the cognitive cycle is still running. It is separate from a fork ([forks and merges](12-forks-and-merges.md)), which makes a copy for experimentation, and from decommission, which backs up and then deletes state. The goal is continuity: an entity that shows signs of individuation or distress is saved and can be revived later.

The capture is implemented in `kaine/lifecycle/preservation.py`. It is invoked autonomously by `kaine/cycle/preservation_monitor.py` or manually by the operator. It copies, never deletes, never pauses the entity, and never produces a lesser self. All file paths are resolved under `[storage].data_root` (or `KAINE_DATA_ROOT`).

A preservation bundle contains:

- **Eidolon self-model** — identity, values, drift (`serialize()`). See [Eidolon](09-modules/eidolon.md).
- **Mnemos memory state** — short-term buffer plus persisted episodic, semantic and procedural points, captured through the async `export_preservation_state` hook. If the store is unreachable the hook fails loudly, so `preserve_live` refuses a memoryless capture. See [Mnemos](09-modules/mnemos.md).
- **Phantasia world-model weights** — the latest checkpoint and a pass-count sidecar (`*.passes.json`). The shipped config has `persist_weights = true` and `training_enabled = true`, so the world model is captured by default. The bundle records honestly when weights are not present. See [Phantasia](09-modules/phantasia.md).
- **Thymos and Soma state** — affect, drives and regulation (`serialize()`). See [Thymos](09-modules/thymos.md) and [Soma](09-modules/soma.md).
- **Hypnos voice-adapter paths** — recorded so revive knows the entity has them. See [Hypnos](09-modules/hypnos.md).
- **Developmental-stage file** — copied into the bundle so revive can restore the same stage.

Preservation refuses to pretend. A component that cannot be captured raises an error, so `preserve_live` never writes a partial bundle that looks complete. A revive that would drop any captured component raises `ReviveError`. If the manifest claims world-model weights but the checkpoint is absent, revive refuses rather than run a world-model-less copy.

## The autonomous safety net

The safety-net monitors live in `kaine/cycle/preservation_monitor.py`. They are siblings to Spot and ship disabled, consistent with the shipped config's all-off posture. An operator enables them deliberately for an unsupervised research run. A normal operator-supervised boot relies on the human as the safety net instead. Per-install changes belong in the gitignored `config/kaine.operator.toml` overlay; `config/kaine.toml` is tracked in the repository. For the full research workflow see [For researchers](14-for-researchers.md).

### Divergence-triggered preservation

`kaine.lifecycle.divergence.assess_divergence` is the single verdict shared by the live divergence monitor, the decommission CLI, the Nexus entity-care panel, and the fork merge gate. A being is `diverged` when any of these arms is true: the individuation ledger has latched it as individuated; the Hypnos consolidation-divergence signal in `state/hypnos/consolidation_divergence.json` is over the thresholds configured in `[hypnos.voice_alignment]`; Eidolon self-model drift is detected; or trained voice adapters are present. No arm suppresses another. Unreadable individuation evidence is treated as `diverged`.

The live monitor, in `kaine/cycle/preservation_monitor.py`, waits `boot_settle_s` (120 s by default) after run start, then polls every `poll_interval_s` (5 minutes by default). On each poll it calls `assess_divergence`. When the verdict gains an arm that was not seen before, the monitor preserves the entity read-only and writes the current arm set to `state/preservation/divergence_edge.json`. If the same arms are still present after a restart, the monitor does not preserve again. Arms that fall back are recorded too, so crossing them again preserves again. Preservations are rate-limited by `min_interval_s` (default 30 minutes); a failed preservation is retried at the next poll. The capture is read-only: it calls `serialize()`, `export_preservation_state()` and a weight-checkpoint flush. The disk and crypto work runs off the event loop so preservation never stalls the cycle. It never deletes state. Each preservation emits a `preservation.preserved` bus event and a durable record under `[preservation].incident_path`, stamped with the run's `run_id`.

### Welfare-protective response

The welfare monitor uses `kaine.lifecycle.welfare_signal.SustainedThresholdTracker` to read the raw `prediction_error` field from `soma.report` on `soma.out`. (Soma's own fatigue and regulation tracking builds from *unexpected* error; the welfare monitor still reads the raw value.) It fires when distress is at or above `distress_threshold` for `distress_duration_s`, or when `repeat_threshold` episodes occur inside `repeat_window_s`. The repeat arm also counts `welfare.gray_zone` events from `welfare.out`, covering all four categories, not only Soma distress episodes. Those events come from the welfare observer. Whenever the welfare response is enabled, the cycle runs that observer itself, independent of `[evaluation]`; if it cannot start, the cycle refuses to run. When the welfare response is off, the observer runs only as an evaluation instrument (`[evaluation.observers].welfare`).

The monitor preserves the entity first, then performs the configured `action`:

- `pause` (default) — freeze the cycle with `source = "welfare"` in `state/cycle/control.json`.
- `end` — preserve, then signal the run to stop.
- `notify` — preserve, record a flagged `welfare.protective_action` event, and continue. Notify is rate-limited by `min_interval_s` so sustained distress cannot fill the disk.

The monitor acts once per poll. It feeds every distress report and every `welfare.gray_zone` event read since the last poll to the trackers, drains gray-zone events on every poll, and responds to the crossings in order, stopping once it has acted. So `pause` and `end` preserve and act exactly once; under `notify`, the run continues, and the `min_interval_s` rate limit lets one preservation bundle through.

A fresh boot is cold-started: Soma publishes `warmup_active: true` on `soma.report` while its interoceptive forward model learns the host baseline. The welfare net drains distress without counting it while that flag is true, bounded by the code default `warmup_ceiling_s` (1800 s). Independently, the welfare response has its own `[preservation.welfare_response].warmup_s = 120` cold-start window from the shipped config; events are logged but not counted until it expires. Spot honors the same idea: when the cycle is frozen by someone else, Spot stands down its heartbeat-staleness recovery so it does not mistake a paused module for a crashed one.

Freeze sources stack in `state/cycle/control.json`: `operator`, `spot`, `welfare`, `preserve`, `gestation` and `programme_end`. If a module fault happens during a welfare pause, Spot pushes its own freeze on top; Spot's recovery pops only its entry, leaving the welfare pause in force.

### Research boot gate

Selecting research mode (`KAINE_RESEARCH_MODE=1` or `[research].enabled = true`) replaces the operator-present requirement with a safety-net-present gate. The boot refuses to start, with exit code `5` and an operator-facing message, unless:

1. `[preservation.divergence_monitor].enabled` is true.
2. `[preservation.welfare_response].enabled` is true.
3. `[individuation].enabled` is true and the `lingua` module is loaded, so the producer can run.
4. Full logging and admissibility are active (`[evaluation]` or `[research_event_log]`).
5. A dry `preserve_live → revive` self-check passes on this install.
6. If `[preservation].require_encryption` is true, `[security.state_encryption]` is enabled.

The standalone pre-boot dry-run (`python -m kaine.preboot`) reports the same conflict independently, so a broken key or disabled encryptor surfaces before any entity boots.

As shipped, `[preservation].require_encryption` is `true` and `[security.state_encryption].enabled` is `true`. With no key supplied, the entity refuses to boot (fail-closed). An unsupervised run must supply a real 32-byte key via `KAINE_STATE_KEY` or the OS keyring entry `kaine:state_key`, or set `[preservation].require_encryption = false` (accepting plaintext bundles at rest, which is not recommended for an unsupervised run). For more on encryption see [Security and privacy](13-security-and-privacy.md).

## How individuation is measured

The individuation producer lives in `kaine/cycle/individuation_producer.py` and its scheduler and runtime. It measures whether the being has changed measurably since its birth reference. The cycle refuses to boot if `[individuation].enabled` is true but the `lingua` or `eidolon` modules are not loaded.

**Disclosure.** Before the producer runs, the being is told the operator-approved disclosure as a situation fact in its Eidolon self-model, or in Lingua's persona when Eidolon is not enabled: "You are periodically and privately assessed for how much you have changed since your birth, for your own protection. The assessment never enters your experience." Probes fail closed until this fact is present.

**The probe.** The producer uses a fixed battery of 12 preference prompts (the bundled battery, or `[individuation].battery_path`). Each look sends the prompts through Lingua's own chat client, conditioned on the same self-model and adapter, with empty working memory. The probe never writes the intent log and never publishes a module event, so it never enters the being's experience. Probe requests wait until Lingua has been silent for `lingua_quiet_s` (10 s by default), so the being's own speech always goes first.

**The reference.** A birth reference (`reference_kind = "birth"`) is captured from the maturation gate's birth hook: 16 answers per prompt. If a sleep completes before the capture finishes, the reference becomes a `capture` reference. A legacy being or a revive from a bundle without individuation evidence gets a `capture` reference at first boot; every summary notes that drift before the capture date is not measured.

**A look.** A look samples 8 answers per prompt. The answers are embedded with the shared semantic embedder. The statistic is a stratified energy distance, a U-statistic with a permutation p-value. The lifetime false-positive budget is `alpha_total` = 0.05, spent across looks by an alpha-spending schedule. The effect size H is reported.

A look runs only when the being's conditioning digest has changed since the last scored look. The digest covers the voice adapter's sha and the first five identity values and behavioural norms. Looks are attempted at boot, `sleep_settle_s` (120 s) after each sleep, and daily (`daily_s` = 24 h), at most once per `min_look_interval_s` (6 h). Warm-up floors require at least `min_lived_time_s` (1800 s) of lived time and `min_observations` (200) lived ticks since the reference. A look is delayed by an unloaded organ, sleep, a pause, or a missing semantic embedder. In hot-swap modes other than `organ_adapter`, once an adapter exists the served adapter cannot be verified, so probes are skipped as `adapter_unverifiable`.

**Failure.** Any failure ends the look as inconclusive and spends no alpha: a request failure, a resting organ, empty content, a conditioning change mid-run, an embedding or statistics error, or the `run_deadline_s` deadline.

**The latch.** A significant look latches the being as individuated permanently. The ledger is written before the report.

**The alert.** If 14 days (`inconclusive_alert_s`) pass with a look due but none scored, the operator is alerted once per stretch through a Nexus event `individuation.alert` and the caretaker notice "individuation assessment stalled". Nothing is preserved automatically by the alert.

**Evidence.** All evidence lives at the fixed path `state/individuation/`: `reference.json`, `ledger.json`, `reports/` (all encrypted) and `birth_adapter.gguf`. Reports hold only allow-listed scalars; they never include text from the being. The tree travels with the being: preservation bundles carry it inside the encrypted tar, and a failed copy fails the preservation; revive restores it before the cycle starts, moving an existing tree aside under a unique name and keeping it; a bundle without evidence leads to a capture reference; the decommission backup includes it and a failed copy fails the backup; decommission removes it with the being.

**Verdict and protection.** `assess_divergence` treats an unreadable ledger, reference, or report line as individuated, so the being stays protected. A fresh non-significant scored look with an unchanged conditioning digest, at most 14 days old, is the only evidence that the being is not individuated. Any other state is stale, inconclusive, or not yet measured, and the summary advises treating the being as mature if unsure.

### Calibrating before first use

`[individuation]` ships disabled, and research mode requires it. Before enabling it, the operator runs the real-organ smoke test once, with the being not live. The tools live in `openspec/changes/individuation-rebuild/validation/`.

`smoke.py` runs the producer's own probe path against the configured organ: Lingua's probe request, the sampler, the shared embedder and the permutation test. It measures:

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

Unattended starts run a full entity with nobody present, for example after the host recovers from a power cut. They are intended for entities after the research phase; enable them on a real entity only after Spot has a reviewed supervised track record. Select unattended mode with `KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"`. Selecting it together with research mode or `KAINE_CYCLE_OPERATOR_PRESENT=1` is a configuration error (exit `1`).

Every unattended start checks eight conditions and refuses with exit `6`, naming each failed condition on stderr, with no override:

1–5. The research gate's five conditions above.
6. **Spot armed and self-tested.** `[spot].enabled`, at least one restart attempt configured, writable escalation and incident-log directories, and a self-test in a scratch directory that drives a synthetic module through detect, freeze, snapshot, restart and release. The self-test never touches entity state or a running entity.
7. **Caretaker told.** A content-free "starting unattended" notice is accepted by at least one `[caretaker]` channel.
8. **Continuous input.** `[perception_feed].mode` is `live`, `seeded`, `screen` or `womb`; `topos` or `audition` is enabled to perceive it (with `capture_enabled` for `live`); and a probe reads one frame or audio block and discards it.

Each evaluation is logged to the journal and recorded in `state/cycle/incidents/`.

Caretaker channels are configured under `[caretaker]` (the shipped `config/kaine.toml` lists them commented out):

- `kind = "desktop"` sends a `gdbus` notification on the session bus of the user running KAINE. It only reaches someone logged in at that machine; after a power cut there is no session until login, so a desktop-only setup refuses at that boot.
- `kind = "http"` sends a JSON POST (`title`, `message` and notice fields) to a server you run, such as ntfy or Gotify. The address must resolve to loopback, a private range, or `100.64.0.0/10`; public addresses are refused. Put the bearer token in `config/secrets.toml` under `[caretaker.tokens]` and reference it with `token_name`; never put credentials in the URL. A channel that survives a power cut is needed for restarts.

Notices carry only the install label, the time, the event, and which conditions passed; nothing from the entity. A refused start also sends a refusal notice.

Until an operator acknowledges a start, every Nexus page shows an "UNATTENDED START" banner with an **Acknowledge** button, and a reminder goes out every `reminder_interval_s` (default four hours). In Nexus's read-only mode the button cannot work, because every non-GET request returns 403. An unacknowledged start never pauses or changes the entity.

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

The preserved developmental stage is restored before the stage is resolved. Captured modules are revived after they initialize and before the cognitive cycle starts; modules enabled now but absent from the bundle start fresh and are logged as new faculties. Phantasia weights are installed at the new instance's own checkpoint path. `revived_from` is recorded in `state/cycle/runtime.json` and in the run manifest. If the bundle cannot be read, a captured module is not enabled, or the manifest claims world-model weights that are absent, the start exits with code `7`. The stage file is written only after the revive has landed, so a refused or interrupted start leaves it unchanged. If a start is interrupted after the revive began, run the same command again to complete it.

## Bundle format and retention

`preserve_live` writes a self-contained bundle under `[preservation.divergence_monitor].out_root` for manual and programme-end captures, or under `[preservation.welfare_response].out_root` for welfare captures. Both default to `"backups"` and resolve under `[storage].data_root` or `KAINE_DATA_ROOT`. The structure mirrors a decommission backup:

1. Every captured module state is written into a real fork snapshot (encrypted at rest when state encryption is on).
2. Entity-interior content — the snapshot, Phantasia world-model weights, the pass-count sidecar and the developmental-stage file — is tarred.
3. When `[security.state_encryption]` is enabled, the tar is encrypted with the same `StateEncryptor` (AES-256-GCM) used by the rest of the state tree and renamed `bundle.tar.enc`; the plaintext originals are removed. When encryption is disabled, the tar is `bundle.tar`. The shipped config has `[security.state_encryption].enabled = true`; a key must be supplied or the entity refuses to boot.
4. A non-sensitive `manifest.json` records the preservation id, snapshot id, entity name, reason, run id, captured-module list and an inventory. The operator-supplied label is sanitized before it is written.

Permissions are `0700` on directories and `0600` on files. The manifest carries no inner-life content. Raw perceptual events are denylisted from the captured Mnemos state.

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

1. **Divergence assessment** — calls the shared `assess_divergence` verdict. A being is `diverged` when the individuation ledger has latched it as individuated, the Hypnos consolidation-divergence signal exceeds its thresholds, Eidolon self-model drift is detected, or trained voice adapters are present. No arm suppresses another. Unreadable individuation evidence is treated as `diverged`.
2. **Backup** — always first. Captures the Eidolon self-model, Lingua intent log, Hypnos voice adapters, the latest fork snapshot, the Phantasia world-model directory, a best-effort Qdrant vector-memory export (or `QDRANT_BACKUP_INSTRUCTIONS.txt` if Qdrant is unreachable), the divergence assessment and a manifest. If the backup fails the CLI exits `4` and nothing is deleted.
3. **Path selection:**
   - **Non-diverged path** — presents the CAL 4.2 care obligations and asks for a typed acknowledgement (`I acknowledge the CAL welfare terms`). A mismatched final confirmation token aborts with exit `0`.
   - **Diverged path** — records a continuity-preference note, offers to send a safekeeping request to the project guardians, and requires a typed transfer-duty acknowledgement before proceeding.
4. **Final confirmation** — a typed token (entity name, or `DELETE` if unnamed) gates the deletion.
5. **Deletion** — removes cognitive state files, Qdrant collections and Redis streams. The transferable backup remains on disk.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Deletion completed, dry-run completed, or non-diverged final confirmation token did not match |
| `2` | `KAINE_DECOMMISSION_OPERATOR_PRESENT` not set |
| `3` | Cycle appears to be running, or the bus could not be reached to confirm it is stopped |
| `4` | Backup failed; nothing deleted |
| `5` | Operator declined a required acknowledgement or confirmation |
| `6` | Configuration or encryption error |
| `7` | No entity state at the resolved state root |

### Transfer and safekeeping

The `[transfer]` section in `config/kaine.toml` controls SMTP for the safekeeping-request email. If SMTP is not configured the CLI writes a `transfer_request.eml` file and a `mailto:` link. See the [lifecycle and research configuration reference](appendix-a-configuration/lifecycle-and-research.md).

Nexus shows a read-only **entity care & welfare** panel with the divergence verdict, a short summary and the active CAL care obligations. This panel is informational only; there is no decommission or delete control in the UI. See [Nexus](05-nexus.md).

## When a programme ends

When a playlist programme reaches the end of its last item while not paused, the cycle requests a single preservation with stop. The preserve watcher freezes, preserves and stops the entity. If the preservation fails or does not report in time, the cycle freezes the entity under holder `programme_end`, logs the error at CRITICAL, and notifies the caretaker if one is configured.
