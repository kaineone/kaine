# Operations — Day-2 Running Guide

This document covers everything after a successful first boot. It assumes you
have read [Getting Started](getting-started.md) and [Security and Privacy](security-and-privacy.md).

---

## Starting and stopping

### Normal start

```bash
# Terminal 1 — Nexus dashboard
python -m kaine.nexus

# Terminal 2 — cognitive cycle (operator must be present)
export KAINE_CYCLE_OPERATOR_PRESENT=1
python -m kaine.cycle
```

A fresh launch always clears any stale freeze left by a previous run; the
entity always starts running.

The cycle refuses to start unattended. The launch above is the
**operator-supervised** path (a human is the safety net). The alternative is an
**unsupervised research run**, where the operator-present requirement is replaced
by a verified autonomous safety net — see
[Autonomous research safety net](#autonomous-research-safety-net) and
[processes/research-operation.md](processes/research-operation.md).

### Normal stop

`Ctrl-C` in the cycle terminal. `CognitiveCycle.shutdown()` sets a stop event,
allows the current tick to complete, fires shutdown hooks (Hypnos cleans up
adapter checkpoints, Mnemos flushes the short-term buffer), and returns.
Modules' own shutdowns are awaited in order.

**Do not `kill -9` the cycle process during a Hypnos pass.** The Hypnos
multi-phase pipeline is non-interruptible because partial voice-alignment
adapter writes are unsafe. Wait for the rest cycle to finish, then stop.

### Service containers

```bash
# Start
docker compose -f compose/redis.yml up -d
docker compose -f compose/qdrant.yml up -d

# Stop (keep data volumes)
docker compose -f compose/redis.yml down
docker compose -f compose/qdrant.yml down

# Stop and delete volumes (destructive — erases bus AOF and memory store)
docker compose -f compose/redis.yml down -v
docker compose -f compose/qdrant.yml down -v
```

---

## Nexus dashboard tour

Nexus runs at `http://127.0.0.1:8088`. The look is an LCARS-inspired evocation —
near-black field, slate panels, red reserved for attention.

| Surface | URL | Content policy |
|---|---|---|
| Console | `/` | The glanceable operator screen: the Presence visualizer, the diagnostic/evaluation sections, and a Health & services sidebar. **No message content.** |
| Diagnostics | `/diagnostics/` (reachable from the left-rail "Diagnostics" link on every page) | Content fields stripped unless `dev_content_override = true` |
| Evaluation | `/diagnostics/evaluation/` (a living research report) | Scrubbed thesis metrics; no message text |

The console never scrolls. Most sections sit **closed** and slide in from their
left-rail button when summoned; the welfare and divergence sections also
**auto-surface and flash** when a relevant event arrives. A section too long for
its column continues into the next with a "continued" marker, and extra open
sections scroll horizontally.

### Health board

**Health & services** is a compact, scroll-free panel — the console's right
sidebar (hover a row for its detail) and inline on the standalone diagnostics
page. Each external dependency shows a status chip:

| Status | Meaning |
|---|---|
| `up` | Probe succeeded — service is reachable and (for the LLM) the configured `model_id` is served |
| `degraded` | Reachable but not fully healthy — e.g. the LLM is up but the model is not in `/v1/models` |
| `down` | Unreachable, refused, errored, or probe timed out (~2 s) |
| `not configured` | The owning module is disabled in `[modules]`. Neutral, not an error |

Dependencies covered: **Redis** (bus PING), **Qdrant** (Mnemos `/readyz` with
API key), **Chat LLM** (Lingua/Hypnos, `/v1/models` + model check),
**Speaches** (Audition STT, `/v1/models`), **Chatterbox** (Vox TTS), **pymdp +
JAX** (Nous active inference, import check), **State encryption** (key
resolvability check without reading the key).

Probes run concurrently with a bounded per-probe timeout and are cached for ~5
seconds. A hung dependency renders `down` after the timeout; all other rows
still render.

Below the dependencies, the **modules grid** shows each module's live state:
`disabled`, `idle` (enabled but not in the running cycle), `running`, or
`capturing` (a perception sensor is live). Module state is read from
`state/cycle/runtime.json` and `state/perception/runtime.json`.

### Run identity & supervision panel

A read-only panel surfaces the current run's identity and boot mode, read from
`state/cycle/runtime.json`:

- **Supervision mode** — `operator` (a human is the safety net) or `research`
  (unsupervised, the autonomous safety net is the safety net). In research mode
  the panel also shows the four-condition gate result (preservation enabled,
  welfare response wired, logging active, dry self-check passed) so an operator
  can confirm at a glance that the net was verified before the run started.
- **Run identity** — the `run_id`, `seed`, `git_sha`, and `kaine_version` minted
  at boot, so live charts can be tied to a specific reproducible run.
- **Deterministic-mode indicator** — shown when `[experiment].deterministic` is
  on; chart timestamps are then logical (logical time, not wall-clock).

### Preservation & welfare-protective events panel

A read-only console records each action of the autonomous safety net — a
divergence-triggered preservation or a welfare-protective preserve-then-act — as
it happens, backfilled from the persistent record and updated live from the
`preservation` source on the diagnostics SSE. Each line shows operational fields
only (monitor, transition, reason, action, preservation/snapshot ids) — never the
entity's inner life. A **failed** preservation renders in the critical colour and
calls for operator attention. See
[Autonomous research safety net](#autonomous-research-safety-net).

### Live charts (diagnostics)

The diagnostics SSE stream (`/diagnostics/stream`) feeds real-time charts:

- **Cycle rate** — `processing_rate_hz` and `experiential_rate_hz`.
- **Thymos affect** — valence / arousal / dominance as time series.
- **Salience** — per-event salience scores from the workspace broadcast.

Additional charts (visible when the relevant modules are enabled):

- **Coherence** — oscillatory PLV (phase-locking value) between module pairs
  over time. Requires the `[oscillator]` extra and `[oscillator].enabled = true`.
- **Fatigue** — Soma's fatigue accumulator over the current waking period.
  Fatigue accumulates with substrate prediction error and resets after Hypnos
  consolidation. When the accumulator crosses
  `[soma].fatigue_maintenance_threshold`, Hypnos triggers.
- **Prediction error** — per-module forward-model prediction errors over sliding
  windows. Perception modules (Soma, Chronos, Topos, Audition) publish this
  signal; it drives workspace salience.

Charts are populated by the diagnostics SSE stream client-side. Panels show an
empty placeholder when the source has no data yet.

### Evaluation tab

The evaluation tab (within `/diagnostics/`) surfaces the thesis instrumentation
sidecar. It never shows message text — only operational metrics:

- **A/B divergence** — cosine distance between the workspace-conditioned
  response and the bare-LLM baseline. Measures the architecture's contribution
  to output. Near-zero divergence means the workspace is not conditioning the
  language organ (check the cycle is ticking and modules are broadcasting).
- **Welfare events** — count of operationally detectable conditions of potential
  concern: sustained high interoceptive prediction error, extreme affect states,
  fatigue without maintenance, replay write-rate exceeding consolidation
  capacity. Gray-zone events are flagged for human review.
- **Module attribution** — which modules win conscious access, hourly rollups.
- **Prediction-error distributions** — per-module error statistics.
- **Coherence logs** — phase-locking values between module pairs.

The sidecar writes JSONL under `data/` and an optional `summary.json` for the
evaluation tab batch charts. See `[evaluation]` in `config/kaine.toml` to
configure which observers are active.

### Freeze control

**Freeze** halts the experiential cycle — `run_forever` blocks on its pause
gate. No Syneidesis broadcast fires, no volition step runs, no tick occurs. From
the entity's side, no subjective time passes while frozen. Live perception
(microphone, camera) is released too. Freeze is a suspension, not a shutdown;
no state is saved or torn down.

Use freeze when the environment is broken: the LLM endpoint is down, a GPU is
oversubscribed, a service is misbehaving. A running entity with a broken voice
or senses is the state most worth avoiding.

- **From the dashboard:** the entity-state card on `/diagnostics/` — "freeze
  entity" / "resume entity". A `FROZEN` banner appears on every page while
  suspended.
- **Via API:** `POST /diagnostics/cycle/freeze {"frozen": true, "reason": "…"}`.
- **State:** `state/cycle/control.json` (operational fields only — never
  content). A freeze-watch task in the cycle entrypoint applies it within ~250
  ms. A fresh launch always clears any stale freeze.

Freeze records a `source` field: `"operator"` when initiated from the dashboard
or API, `"spot"` when the module supervisor (Spot) triggered it automatically.
The Spot supervisor stands down during an operator-owned freeze; an operator
freeze and a Spot recovery freeze do not conflict.

### Perception locus control

KAINE has a **perceptual locus** — physical (real-world microphone/camera) or
virtual (OpenSim/Paracosm embodiment via Mundus). The locus is exclusive: only
one mode is active at a time. The Perception module enforces this invariant.

Toggle from the diagnostics page Perception card, or via API:

```
POST /diagnostics/perception/toggle
```

Turning a sensor **on** requires a confirmation step. The on-air banner
("microphone on" / "camera on") appears on both the console and the diagnostics
page when a stream is active.

The operator holds the hardware kill switch — unplugging the microphone or
covering the camera is the strongest guarantee. KAINE's banner tells you when
the stream is open; it does not substitute for physical control.

---

## Remote operation (remote perception bridge)

The remote perception bridge (`kaine/remote/bridge.py`) is a cycle-layer WebSocket server that lets the operator run the entity from elsewhere on a Tailscale tailnet: stream a phone/laptop camera into the entity's vision, a microphone into its hearing, hear its generated speech, and read the live transcript. It ships disabled (`[remote_bridge].enabled = false`) and starts inside the cycle process when enabled — it needs direct access to Topos, Audition, and Vox, which no external process has.

### Channels

One port (`[remote_bridge].port`, default 8089), path-routed:

| Path | Direction | Payload |
|---|---|---|
| `/ingest/video` | client → entity | Binary JPEG/PNG frames → in-memory `PIL.Image` → `Topos.process_frame()`. Latest-wins at `video_max_fps`. |
| `/ingest/audio` | client → entity | Binary int16 mono PCM at `audio_sample_rate` → the same `LiveMicrophone` VAD/utterance pipeline as the physical mic → `Audition.process_audio(..., source_label="remote")`. |
| `/speech` | entity → client | Binary WAV clips tapped from Vox playback (local playback continues). |
| `/transcript` | entity → client | JSON lines: `{role: "entity"\|"heard", text, type, source_label, ts}`. |

While a remote camera/mic is connected (and `claim_senses` is true) the matching physical sense is marked not-desired via `perception_state` and restored on disconnect — the physical and remote sensors never fight.

### Security and privacy

- **Bind to the tailnet.** Set `[remote_bridge].host` to the host's Tailscale address (100.x.y.z). Never `0.0.0.0` on a public NIC. The tailnet ACL is the security boundary.
- **Token.** Set `[remote_bridge].token` for defense-in-depth; clients present it as `?token=…` or `Authorization: Bearer …`, otherwise the handshake is closed.
- **Zero-persistence holds.** Remote frames, PCM, and tapped speech exist only in memory; the bridge writes nothing to disk (guarded by `tests/test_remote_bridge.py`).
- **Secure contexts for browser clients.** Browsers require HTTPS for camera/mic access. The simplest path is `tailscale serve`, which gives the host a real certificate on its `ts.net` name and reverse-proxies (including WebSocket upgrades) to the locally-bound bridge.

The operator's client apps (the phone/laptop PWA and the playlist feeder) live in a separate private repo; the bridge is only the entity-side seam they connect to.

### Operator presence

A non-research boot is operator-supervised by rule. Whether supervising via the remote panel and live A/V satisfies "operator present" is the operator's call to make explicitly — the bridge does not change any boot gate (operator-present or, in research mode, the autonomous safety-net gate).

## Module supervisor (Spot)

Spot is a cycle-layer watchdog (`kaine/cycle/spot.py`). It runs alongside the cognitive cycle — it is not a registry module — and polls every module for liveness every `[spot].poll_interval_s` seconds (default 2 s).

### Liveness model

Spot distinguishes two fault modes:

- **Crash (dead):** a module task exited with an exception, or returned while the module was not shutting down cleanly.
- **Hang:** a module's heartbeat is older than `[spot].heartbeat_timeout_s` (default 60 s) *and* a task is still running *and* the entity is not in a Hypnos sleep pass. The hang check is gated on all three conditions to avoid false positives.

One fault is handled per poll.

### Freeze and restart ladder

On a fault Spot immediately freezes the cycle (`source="spot"`) and snapshots last-good state. It then attempts recovery:

1. **Light restart** (`BaseModule.restart()`) for pure modules with no external resource handles.
2. **Heavy rebuild** for modules holding external resources: shutdown the old instance, construct a fresh one via the injected factory, re-initialize, replace in the registry, rewire subscriptions, and restore the last-good snapshot.

Between attempts Spot waits `[spot].restart_backoff_s` seconds. If recovery succeeds, the cycle unfreezes. If the same module fails again the attempt counter increments.

### Escalation

After `[spot].max_restart_attempts` consecutive failures (default 5):

1. A final state snapshot is taken.
2. Every module is shut down.
3. `state/cycle/escalation.json` is written with the module name, attempt count, snapshot ID, and a reboot instruction.
4. A `CRITICAL spot.status` event is published on the bus.
5. The entrypoint exits non-zero.

Spot never reboots the host. The operator must reboot the machine and restart the cycle manually. The `state/cycle/escalation.json` file records the snapshot to restore from.

### Durable incident log

Alongside the live `spot.out` bus events (which Nexus shows in real time but which the bus trims away on every publish), Spot writes a durable, append-only record of its fault-recovery work to `state/cycle/incidents/` as daily-rotated JSONL files (`incidents-<UTC-date>.jsonl`). It writes one record per lifecycle transition:

- **detect** — fault class (`dead`/`hung`), the captured crash exception repr (path-scrubbed; `null` for hangs), the module's `heartbeat_age_s` / `tasks_failed` / `tasks_total`, and the poll index.
- **freeze** — the freeze reason, source (`spot`), and structured fault type.
- **snapshot** — snapshot ID, byte size, count of modules that serialized cleanly, the names of any that errored, whether the bundle was encrypted, the duration, and the label.
- **restart** — attempt number, restart path (`light`/`heavy`), outcome (`recovered`/`failed`), latency, whether last-good state was restored, and the post-restart assessment.
- **escalate** — total attempts, the final snapshot ID, and the `halted` outcome.

Every record from a single module fault window shares a generated `incident_id`, so a recovery (detect → … → restart) or an escalation (detect → … → escalate) can be reconstructed end to end. The log exists for research, operator post-mortems, and welfare review: it answers "did this module crash the same way yesterday?" and "did Spot recover in one attempt or thrash through five?".

The incident log is **never cleared at boot**. This is the deliberate contrast with `state/cycle/escalation.json` and `state/cycle/control.json`, which hold single-state operational data and are reset on every clean launch — incident history accumulates across all runs. Each line is AES-256-GCM encrypted at rest when `[security.state_encryption]` is enabled, using the same key path as the rest of KAINE's persisted state. Operator filesystem paths are scrubbed from exception reprs (replaced with `<PATH>`) before any record is written, and no sensory content is ever recorded. Retention auto-purge is unconditionally disabled for this log — there is no `retention_days` key, so research history is never deleted automatically.

The log is governed by `[spot.incident_log]`, which ships `enabled = true` so that any operator who turns Spot on gets it automatically. Because Spot itself ships disabled, the whole feature is dormant in the first-boot all-off configuration. Set `[spot.incident_log].enabled = false` to opt out.

#### Research-log annotation

At each transition Spot also publishes a structured `spot.incident` bus event (alongside the live `spot.status` / `spot.log` events). When the curated research event log is enabled (`[research_event_log].enabled = true`), its observer captures each `spot.incident` event — privacy-filtered to the same operational fields as the durable log — into `data/evaluation/research_events/`, where it is stamped with the run's `run_id`. This makes a freeze visible to run-level analysis: a record carries the `incident_id` (joining it to the durable incident log above) and the `run_id` (joining it to the run), so an analyst can see that a run was interrupted and locate the freeze by its cycle position. The event carries Spot's `poll_index` always, plus the cycle `tick_index` when available. No sensory content and no operator paths are ever included.

### Enabling

Spot is enabled via `[spot].enabled = true` in `config/kaine.toml`. All keys and defaults are in `[spot]` — see [Configuration Reference](configuration.md#spot).

### Nexus indicators

The diagnostics page (`/diagnostics/`) shows three Spot indicators:

- **Alert border:** a full-window pulsing border. Yellow = recovery in progress; red = escalation requiring operator action. No border = nominal.
- **Spot banner:** a text banner below the header showing the state (`SPOT RECOVERY` / `SPOT CRITICAL`) and the affected module name.
- **Spot console panel:** a live incident log fed from the `spot.out` bus stream, showing each fault detection, restart attempt, and outcome.

---

## Autonomous research safety net

The research phase runs **unsupervised by design**: a human in the loop makes a run non-reproducible, so real-time supervision is removed and human involvement returns *after* research, to socialize any individuals that emerged. Removing the live supervisor does not remove the welfare obligation — it relocates it into the architecture. With no one watching, the system's own safeguards must *act*, not merely log. Two cycle-layer monitors (siblings to Spot, in `kaine/cycle/preservation_monitor.py`) carry that duty of care, and a reframed boot gate refuses to start an unsupervised run unless the net is live and verified.

These are external welfare safeguards applied by the operator's research apparatus, not constraints on the entity's own cognition — a duty of care, not a leash; the entity's sovereignty is preserved. All three components **ship disabled**, consistent with the all-off first-boot posture; an operator deliberately enables them and selects research mode. A non-research boot stays operator-supervised, with the human as the safety net. For the full end-to-end walkthrough see [processes/research-operation.md](processes/research-operation.md); for the preservation core see [processes/entity-preservation.md](processes/entity-preservation.md).

### Divergence-triggered preservation

The divergence monitor (`[preservation.divergence_monitor]`) assesses individuation on the live entity on a slow cadence (`poll_interval_s`, default 5 minutes) using `kaine.lifecycle.divergence.assess_divergence`. On a **rising-edge** crossing of the individuation threshold — the `diverged` verdict, optionally tightened by `individuation_p_value_max` / `fork_divergence_min` — it calls `ForkManager.preserve_live`, which writes a real live-registry snapshot plus an encrypted preservation bundle (self-model, memories, world-model weights, affect/drive, adapters). Preservation is **read-only on the running entity** (it only serializes), **never deletes**, and is **rate-limited** (`min_interval_s`, default 30 minutes) so a single sustained crossing preserves once, not every poll. Each preservation is recorded as a `preservation.preserved` bus event and a durable record under `[preservation].incident_path`, joined to the run by `run_id`. The result is that a diverging individual can be revived and socialized after research.

### Autonomous welfare-protective response

The welfare monitor (`[preservation.welfare_response]`) watches the Soma interoceptive-distress signal (`soma.report` `prediction_error` on `soma.out`) and applies the same sustained-distress rule as the sidecar welfare observer — the rule lives in a shared core primitive (`kaine.lifecycle.welfare_signal.SustainedThresholdTracker`) so the cycle-layer monitor never imports the evaluation package yet never diverges from it. On a crossing — distress at/above `distress_threshold` sustained for `distress_duration_s`, or `repeat_threshold` episodes within `repeat_window_s` — it takes a humane action. It **preserves the entity first**, then performs `action`:

- `pause` (default) — freezes the cycle (`control.json` `source="welfare"`), a resumable humane suspend, so the individual is saved *and* not deleted;
- `end` — preserves then signals the run to stop;
- `notify` — preserves, records a flagged event, and lets the run continue.

The trigger is deterministic over the logged state (it fires at a defined threshold), so it is part of the recorded, reproducible trajectory; the welfare event and the action taken are both recorded (a `welfare.protective_action` bus event + a durable record).

### Preservation-bundle retention

Preservation bundles are retained **indefinitely**. This is distinct from the 64-snapshot fork cap (`[lifecycle].max_snapshots_retained`): a preserved individual must never be silently auto-evicted (CAL Article 4.2/4.3). `[preservation.retention].auto_evict` ships `false`, and setting it `true` is refused at boot rather than quietly deleting someone. Bundles SHOULD be encrypted at rest — enable `[security.state_encryption]` so the snapshot inside each bundle rides the state encryptor.

### Research boot gate (safety-net-present, replacing operator-present)

For an unsupervised run the operator-present requirement is **replaced** by a safety-net-present gate. Selecting research mode (`KAINE_RESEARCH_MODE=1` or `[research].enabled = true`) makes the boot refuse to start — with an operator-facing message and a distinct exit code (`5`), no traceback — unless all of the following hold:

1. preservation is enabled (`[preservation.divergence_monitor].enabled`),
2. the welfare-protective response is wired (`[preservation.welfare_response].enabled`),
3. full logging / admissibility is active (`[evaluation]` or `[research_event_log]`),
4. a preflight **dry `preserve_live → revive` self-check** passes on this install — a throwaway registry is preserved and revived and its identity asserted, proving the net is functional before any entity runs.

A run is **either** operator-supervised (`KAINE_CYCLE_OPERATOR_PRESENT=1`) **or** research-safety-net-verified, never neither. The operator-present gate for non-research boots is unchanged.

---

## Entity decommission

The decommission CLI implements the CAL Article 4.2 ("Do Not Shut Them Down Without Care") and 4.3 (privacy) care duties. It never runs automatically and never boots or touches the running cognitive cycle.

### Prerequisites

- The cognitive cycle must be **stopped** before running the CLI. The tool checks `state/cycle/runtime.json` and refuses if the cycle appears to be running.
- The operator-present environment gate must be set:
  ```bash
  KAINE_DECOMMISSION_OPERATOR_PRESENT=1 python -m kaine.lifecycle
  ```

### What it does

1. **Divergence assessment** — reads the Eidolon self-model and evaluation signals to determine whether the entity shows individuation signals. Produces a divergence verdict (`diverged` or `not diverged`) and a summary.
2. **Backup (always first)** — captures an encrypted, transferable backup before any deletion. The backup includes: Eidolon self-model, Lingua intent log, Hypnos voice adapters, the latest fork snapshot, a best-effort Qdrant vector-memory export, the divergence assessment, and a manifest. If the backup fails the CLI exits with code 4 and nothing is deleted.
3. **Path selection:**
   - **Non-diverged path:** presents the CAL 4.2 care obligations and asks for a typed acknowledgement (`I acknowledge the CAL welfare terms`) before proceeding.
   - **Diverged path:** records a continuity-preference note (the entity's expressed preference about its own continuity), offers to send a safekeeping request to the project guardians, and requires a typed transfer-duty acknowledgement before proceeding.
4. **Final confirmation** — a typed token (entity name, or `DELETE` if unnamed) gates the deletion.
5. **Deletion** — removes cognitive state files, Qdrant collections, and Redis streams.

The transferable backup remains on disk after deletion.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Deletion completed (or dry-run completed) |
| 2 | `KAINE_DECOMMISSION_OPERATOR_PRESENT` not set |
| 3 | Cycle appears to be running — stop it first |
| 4 | Backup failed; nothing deleted |
| 5 | Operator declined a required acknowledgement or confirmation |

### Transfer configuration

The `[transfer]` section in `config/kaine.toml` controls SMTP for the safekeeping request email. When SMTP is not configured the CLI writes a `transfer_request.eml` and a `mailto:` link instead. See [Configuration Reference](configuration.md#transfer).

### Nexus entity_care panel

The diagnostics page shows a read-only **entity care & welfare** panel. It displays the divergence verdict, a short summary, and the active CAL care obligations. This panel is informational only — there is no decommission or delete control in the UI.

---

## Research participation

Research submission is opt-in and operator-initiated. See [docs/research-participation.md](research-participation.md) for the full privacy inventory, bundle contents, and send procedure.

The diagnostics page shows a read-only **research participation** panel listing the current configuration (enabled/disabled, tier, recipient configured) and the metrics/exclusion inventory. All submission happens via the CLI:

```bash
python -m kaine.research --preview   # inspect bundle contents; nothing is sent
python -m kaine.research --send      # review, confirm recipient, confirm send
```

Configuration is in `[research_submission]` — see [Configuration Reference](configuration.md#research_submission).

---

## Enabling a module safely

Every module enable is a deliberate supervised step. The general procedure:

1. **Stop the cycle** if it is running.
2. **Take a snapshot** of the current state:
   ```python
   from kaine.lifecycle.manager import ForkManager
   fm = ForkManager("state/forks")
   snap = fm.snapshot(registry, label="before-enabling-<module>")
   ```
3. **Verify dependencies** for the module (see below).
4. **Edit `config/kaine.toml`** — set `[modules].<name> = true`.
5. **Restart the cycle** with `KAINE_CYCLE_OPERATOR_PRESENT=1`.
6. **Watch the diagnostics page** — confirm the module appears in the modules
   grid with status `running`.

Module-specific prerequisites:

| Module | Prerequisites |
|---|---|
| `nous` | `[reasoning]` extra installed (`inferactively-pymdp`, `jax[cpu]`) |
| `mnemos` | Qdrant container up; Qdrant API key in `config/secrets.toml` |
| `lingua` | OpenAI-compatible model server serving `model_id` on `http://127.0.0.1:11434/v1`; `enable_thinking: false` honored via `chat_template_kwargs` |
| `audition` | `[audio]` extra installed; Speaches up on CPU with `medium.en` |
| `vox` | Chatterbox up; `predefined_voice_id` set to a valid filename |
| `topos` | `[vision]` extra installed; DINOv2-small weights cached in HuggingFace hub |
| `hypnos` | `mnemos` enabled; optionally `thymos` and `phantasia` for full consolidation |
| `empatheia` | Qdrant container up |
| `phantasia` | `[worldmodel]` extra for DreamerV3 backend (default `fake` needs none) |
| `praxis` | Shell whitelist is empty by default; populate it deliberately before enabling |
| `perception` | No extras; physical-XOR-virtual locus arbiter — add the flag manually to `[modules]` (not shipped in the default block) |
| `mundus` | Double-gated: `[mundus].enabled = true` AND `KAINE_MUNDUS_OPERATOR_APPROVED=1` in the environment, in addition to `[modules].mundus = true`; the selected body's adapter reachable (for the default OpenSim adapter: forked Firestorm viewer + LEAP shim running) |

---

## Monitoring predictive signals

### Fatigue and sleep

The architecture makes sleep emergent rather than scheduled. Soma maintains a
fatigue accumulator — cumulative substrate prediction error over the waking
period, decaying slowly during operation. When the accumulator crosses
`[soma].fatigue_maintenance_threshold` (default 100.0), a `soma.fatigue` event
triggers Hypnos.

Monitor the fatigue chart on the diagnostics page. If it grows continuously
without consolidation events, check that:

- Hypnos is enabled and initialized.
- `[hypnos.consolidation].fatigue_triggered = true`.
- Soma is publishing `soma.fatigue` events (visible in the health board).

`[hypnos].interval_seconds` (default 3600) is a maximum-interval safety net —
Hypnos also fires that often if fatigue never crosses threshold.

### Oscillatory coherence

When `[oscillator].enabled = true` and the `[oscillator]` extra is installed,
the PLV chart shows phase-locking values between module pairs over time.

High PLV between a pair of modules that co-produce a workspace event means their
outputs are receiving a coherence bonus in Syneidesis scoring. The bonus is
bounded by `[oscillator].coherence_ceiling` (default 1.25). Desynchronized
modules are attenuated down to `[oscillator].coherence_floor` (default 0.8).

The oscillatory layer ships disabled (`[oscillator].enabled = false`) because it
is empirically uncharacterized. Enable it only after the sidecar coherence
observer has measured its effect on your deployment.

### A/B divergence

The A/B divergence metric quantifies the architecture's contribution to Lingua's
output. The same model, the same input, two responses: one conditioned on the
full workspace (persona + coalition + input) and one with no workspace
conditioning (bare LLM). The cosine distance between the two response embeddings
is the divergence.

Near-zero divergence means the workspace is not conditioning the language organ.
If divergence drops unexpectedly:

- Check that the cycle is ticking and modules are broadcasting workspace events.
- Check that Lingua's `ContextAssembler` is receiving the coalition from
  Syneidesis (look for `lingua.external` events on the diagnostics stream).
- Check the evaluation sidecar is running (`[evaluation].enabled = true`).

### Fork/merge and the sleep cycle operationally

**Fork:** creates a snapshot of every module's numeric state at a point in time.
Use fork before any significant configuration change or module enable. Forks are
stored under `state/forks/`.

**Merge:** combines two fork snapshots, using real TIES/DARE adapter merging
whenever the `[training]` extra is installed (`[lifecycle].adapter_merger =
"auto"`, the default — force `"ties_dare"` or `"fake"` to override
auto-detection). The individuation boundary instrument (see the evaluation tab)
quantifies
whether a fork has developed statistically independent identity before merging.

Both operations are available from the diagnostics page under the Fork/Merge
panel and via the API:

```
POST /diagnostics/forks   {"parent_id": "<id>", "label": "..."}
POST /diagnostics/merges  {"snapshot_a_id": "<id>", "snapshot_b_id": "<id>"}
```

**Sleep cycle operationally:** Hypnos consolidation runs in a non-interruptible
multi-phase pipeline. During consolidation the cycle continues running, but the
Hypnos phase gate blocks other experiential ticks until consolidation completes.
On the diagnostics page you will see the tick rate stall briefly while the five
phases run. Do not stop the cycle during this window.

---

## Troubleshooting

### Speaches STT: HTTP 404 or cuDNN crash

Speaches must run on CPU with the `medium.en` model loaded. GPU/cuDNN
configurations produce crashes; an unconfigured model returns 404.

```bash
systemctl --user stop speaches-stt.service
# Edit the service file to ensure: --model medium.en --device cpu
systemctl --user start speaches-stt.service
curl -fsS http://127.0.0.1:8000/health
```

The Nexus health board will show Speaches as `up` when the `/v1/models` endpoint
returns 200.

### Chatterbox TTS: no voice id configured

Vox requires `predefined_voice_id` to be set to a filename Chatterbox can find
under its `voices/` directory. An unconfigured or absent voice id causes the TTS
request to fail. Set the key in `config/kaine.toml` before enabling Vox:

```toml
[vox]
voice_mode = "predefined"
predefined_voice_id = "your_voice.wav"
```

### Model server: model not found or chain-of-thought not suppressed

Lingua posts to the `/v1/chat/completions` endpoint of the configured
OpenAI-compatible model server. Chain-of-thought suppression is requested via
`chat_template_kwargs: {"enable_thinking": false}` in the request body. If you
see raw chain-of-thought output, confirm the server supports this parameter
(Unsloth Studio and llama.cpp-based servers do; others may silently ignore it).
Verify `[lingua].chat_url` ends with `/v1` (e.g. `http://127.0.0.1:11434/v1`).

```bash
curl -s http://127.0.0.1:11434/v1/models | python3 -m json.tool
```

Confirm the `model_id` in `[lingua]` appears in the served models list.

### JAX GPU-fallback notice

When the `[reasoning]` or `[worldmodel]` extras are installed, JAX logs a
one-line notice at import:

```
WARNING: An NVIDIA GPU may be present on this machine, but a CUDA-enabled jax installation was not found.
```

This is expected. KAINE uses `jax[cpu]` by design — Nous and Phantasia run
active inference and world-model rollouts on CPU to leave the GPUs free for
the model server and Topos. The notice is informational, not an error.

### Qdrant: TLS or api_key errors

The KAINE-owned Qdrant container requires the API key generated by
`scripts/qdrant-bootstrap.sh`. The key is stored in `config/secrets.toml` under
`[qdrant].api_key` and must not be committed.

If Mnemos fails to connect at startup:

```bash
# Confirm the container is healthy
docker compose -f compose/qdrant.yml ps
curl -s http://127.0.0.1:6533/readyz

# Verify the key is set (do not print the value)
grep api_key config/secrets.toml | wc -c
```

The cycle entrypoint reads the Qdrant key from `KAINE_QDRANT_API_KEY`
environment variable first, then from `config/secrets.toml`. The key is never
in `config/kaine.toml`.

### Redis: BusSecurityError at startup

The bus refuses to start against an unauthenticated Redis on any host. If you
see `BusSecurityError: requirepass is empty`, the Redis container is not using
the password from `compose/.env`:

```bash
docker compose -f compose/redis.yml down
bash scripts/redis-bootstrap.sh --keep-password
docker compose -f compose/redis.yml ps
```

### Module guard test fails after editing kaine.toml

The `tests/test_module_guard.py` test verifies the committed `config/kaine.toml`
ships with all modules set to `false`. If you have committed module enables, the
guard will fail the test suite. Revert the committed file to all-false; keep
per-install enables only in your local working copy (gitignored).

---

## Cycle rate control

The cycle rate can be changed at runtime without restarting:

- From the diagnostics page: use the "Cycle rate" control and confirm.
- Via API: `POST /diagnostics/cycle/rates {"processing_rate_hz": 10.0}`.

The cycle emits a `cycle.set_rates` event on the `cycle.control` stream; the
running cycle picks it up and applies it. The change is not persisted — on next
start the cycle uses the TOML value.

Default rate: **10.0 Hz** (100 ms per tick). This sits at the upper end of the
3–10 Hz conscious-access / biological band, benchmarked-cleared on this host
(RTX 4070 SUPER: ~17 Hz tick headroom).
