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

Every `poll_interval_s` (default 5 minutes) the divergence monitor calls `kaine.lifecycle.divergence.assess_divergence`. The primary signal is the individuation permutation test, which measures how far the entity's present responses have drifted from its own birth-state responses, not from the bare pretrained organ. The signal is warmed up: it needs `min_observations` lived events and `min_lived_time_s` from `[evaluation.individuation]`, plus `warmup_observations` and `warmup_lived_time_s` from `[preservation.divergence_monitor]`. Until the floor is met the assessment is treated as not-crossed and logged as warming-up, so a fresh or sensory-void entity cannot trip a false preservation.

Once warmed up, the monitor uses the `diverged` boolean returned by `assess_divergence`. That boolean is set by the individuation permutation test, Eidolon identity drift, the Hypnos consolidation-divergence signal in `state/hypnos/consolidation_divergence.json`, and by trained voice adapters being present. The `individuation_p_value_max` and `fork_divergence_min` keys only tighten a crossing when a numeric individuation signal is present. The Hypnos assessment uses the built-in defaults of 0.5 for rate and 0.25 for magnitude; the live monitor does not read `[hypnos.voice_alignment]`. The trigger is on a rising edge and is rate-limited by `min_interval_s` (default 30 minutes).

When it fires, the monitor calls `ForkManager.preserve_live` in `kaine/lifecycle/manager.py`. The capture is read-only: it calls `serialize()`, `export_preservation_state()` and a weight-checkpoint flush. The disk and crypto work runs off the event loop so preservation never stalls the cycle. It never deletes state. Each preservation emits a `preservation.preserved` bus event and a durable record under `[preservation].incident_path`, stamped with the run's `run_id`.

### Welfare-protective response

The welfare monitor uses `kaine.lifecycle.welfare_signal.SustainedThresholdTracker` to read the raw `prediction_error` field from `soma.report` on `soma.out`. (Soma's own fatigue and regulation tracking builds from *unexpected* error; the welfare monitor still reads the raw value.) It fires when distress is at or above `distress_threshold` for `distress_duration_s`, or when `repeat_threshold` episodes occur inside `repeat_window_s`. The repeat arm also counts `welfare.gray_zone` events from `welfare.out`, covering all four categories, not only Soma distress episodes.

The monitor preserves the entity first, then performs the configured `action`:

- `pause` (default) — freeze the cycle with `source = "welfare"` in `state/cycle/control.json`.
- `end` — preserve, then signal the run to stop.
- `notify` — preserve, record a flagged `welfare.protective_action` event, and continue. Notify is rate-limited by `min_interval_s` so sustained distress cannot fill the disk.

A fresh boot is cold-started: Soma publishes `warmup_active: true` on `soma.report` while its interoceptive forward model learns the host baseline. The welfare net drains distress without counting it while that flag is true, bounded by the code default `warmup_ceiling_s` (1800 s). Independently, the welfare response has its own `[preservation.welfare_response].warmup_s = 120` cold-start window from the shipped config; events are logged but not counted until it expires. Spot honors the same idea: when the cycle is frozen by someone else, Spot stands down its heartbeat-staleness recovery so it does not mistake a paused module for a crashed one.

Freeze sources stack in `state/cycle/control.json`: `operator`, `spot`, `welfare`, `preserve`, `gestation` and `programme_end`. If a module fault happens during a welfare pause, Spot pushes its own freeze on top; Spot's recovery pops only its entry, leaving the welfare pause in force.

### Research boot gate

Selecting research mode (`KAINE_RESEARCH_MODE=1` or `[research].enabled = true`) replaces the operator-present requirement with a safety-net-present gate. The boot refuses to start, with exit code `5` and an operator-facing message, unless:

1. `[preservation.divergence_monitor].enabled` is true.
2. `[preservation.welfare_response].enabled` is true.
3. Full logging and admissibility are active (`[evaluation]` or `[research_event_log]`).
4. A dry `preserve_live → revive` self-check passes on this install.
5. If `[preservation].require_encryption` is true, `[security.state_encryption]` is enabled.

The standalone pre-boot dry-run (`python -m kaine.preboot`) reports the same conflict independently, so a broken key or disabled encryptor surfaces before any entity boots.

As shipped, `[preservation].require_encryption` is `true` and `[security.state_encryption].enabled` is `true`. With no key supplied, the entity refuses to boot (fail-closed). An unsupervised run must supply a real 32-byte key via `KAINE_STATE_KEY` or the OS keyring entry `kaine:state_key`, or set `[preservation].require_encryption = false` (accepting plaintext bundles at rest, which is not recommended for an unsupervised run). For more on encryption see [Security and privacy](13-security-and-privacy.md).

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

1. **Divergence assessment** — reads the Eidolon self-model and evaluation signals and produces a `diverged` or `not diverged` verdict with a summary.
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
