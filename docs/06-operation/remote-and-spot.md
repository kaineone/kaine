# Remote operation and the Spot supervisor

Use this page to operate KAINE from another device over a tailnet, or to turn on automatic module supervision. It covers the remote perception bridge and Spot, the cycle-layer watchdog that detects and recovers from module faults.

## Remote perception bridge

The remote perception bridge is [`kaine/remote/bridge.py`](../../kaine/remote/bridge.py). It is a WebSocket server that runs inside the cycle process, because only that process can reach [Topos](../09-modules/topos.md), [Audition](../09-modules/audition.md) and [Vox](../09-modules/vox.md) directly.

The shipped config disables the bridge (`[remote_bridge].enabled = false`). Enable it in `config/kaine.operator.toml`.

### Channels

The bridge listens on one port, `[remote_bridge].port` (default `8089`), with separate paths for each direction:

| Path | Direction | Payload |
|---|---|---|
| `/ingest/video` | client to entity | Binary JPEG or PNG frames. The bridge converts each frame to an in-memory `PIL.Image` and passes it to `Topos.process_frame()`. Only the latest frame is kept, capped at `video_max_fps` (4.0). |
| `/ingest/audio` | client to entity | Binary int16 mono PCM at `audio_sample_rate` (16000). It goes through the same voice-activity and utterance pipeline as the physical microphone, then to `Audition.process_audio(..., source_label="remote")`. |
| `/speech` | entity to client | Binary WAV clips tapped from Vox playback. Local playback continues. |
| `/transcript` | entity to client | JSON lines: `{role: "entity"\|"heard", text, type, source_label, ts}`. |

While a remote camera or microphone is connected and `claim_senses` is true (the default), the matching physical sense is marked not desired through `perception_state`, and it is restored when the remote client disconnects.

### Security and privacy

- Bind to the tailnet. The default host is `127.0.0.1`. For remote clients, set `[remote_bridge].host` to the host's Tailscale address (`100.x.y.z`), and never use `0.0.0.0` on a public interface. The tailnet ACL is the access boundary.
- Set a token. Clients send `[remote_bridge].token` as `Authorization: Bearer <token>`. Tokens in the query string or in `Sec-WebSocket-Protocol` are rejected, so the secret does not end up in logs or browser history. Without a token, the bridge refuses to bind a non-loopback host.
- Nothing is persisted. Remote frames, PCM and tapped speech live only in memory, and the bridge writes nothing to disk; [`tests/test_remote_bridge.py`](../../tests/test_remote_bridge.py) checks this.
- Browsers need a secure context. They require HTTPS before they grant camera and microphone access. The simplest setup is `tailscale serve`, which gives the host a real certificate on its `ts.net` name and reverse-proxies WebSocket upgrades to the locally bound bridge.

The operator client apps, a phone or laptop PWA and a playlist feeder, live in a separate private repository. The bridge is only the entity-side endpoint they connect to.

### Operator presence

A boot outside research mode is either operator-supervised (`KAINE_CYCLE_OPERATOR_PRESENT=1`) or unattended, which passes the gate in `kaine/cycle/unattended_gate.py`. Whether supervising through the remote panel and live audio and video counts as an operator being present is the operator's explicit decision. The bridge changes none of the boot gates: the operator-present check, the unattended gate and the research-mode gate all apply as before.

## Module supervisor (Spot)

Spot is the cycle-layer watchdog in [`kaine/cycle/spot.py`](../../kaine/cycle/spot.py), outside the module registry. It polls every module for liveness every `[spot].poll_interval_s` seconds (2 by default).

The shipped config disables Spot (`[spot].enabled = false`). Enable it in `config/kaine.operator.toml`.

### Liveness model

Spot distinguishes two fault modes:

- A crash (`dead`): a module task exited with an exception, or returned while the module was not shutting down.
- A hang (`hung`): the module's heartbeat is older than `[spot].heartbeat_timeout_s` (60 s by default) while a task is still running and the entity is not in a [Hypnos](../09-modules/hypnos.md) sleep.

Spot handles one fault per poll.

A frozen cycle's modules are silent, so Spot stays out of any freeze it does not hold itself. The one exception is a freeze held only by `gestation` (set when the gestational stimulus is lost; see [Gestation](./gestation.md)), during which Spot repairs crashes and ignores hangs.

### Freeze and restart ladder

On a fault, Spot freezes the cycle under its own holder (`spot`) and, on the first attempt, snapshots the last good state. It then tries to recover the module:

1. A light restart calls `BaseModule.restart()`, for modules that hold no external resources.
2. A heavy rebuild, for modules that hold external resources, shuts down the old instance, builds a fresh one through the injected factory, initializes it, replaces it in the registry, rewires its subscriptions and restores the last good snapshot.

Between attempts Spot waits `[spot].restart_backoff_s` seconds (3 by default). When recovery succeeds, Spot releases its freeze. When the same module fails again, the attempt count rises.

### Escalation

After `[spot].max_restart_attempts` failed attempts (5 by default), Spot:

1. takes a final state snapshot;
2. writes `state/cycle/escalation.json` under the data root, with the module name, the attempt count, the snapshot id and a reboot instruction;
3. publishes a critical `spot.status` event;
4. signals the entrypoint to halt and shuts down every module, and the entrypoint exits with a non-zero status.

Spot never reboots the host. The operator reboots the machine and restarts the cycle, and `escalation.json` names the snapshot to restore from.

### Durable incident log

Spot writes an append-only log of its fault-recovery work to `state/cycle/incidents/incidents-<UTC-date>.jsonl` under the data root. It is separate from the live `spot.out` bus events that Nexus shows: the bus streams are trimmed on every publish, and the incident log is kept on disk for research, operator post-mortems and welfare review.

Each lifecycle transition produces one record:

| Transition | What is recorded |
|---|---|
| `detect` | Fault class (`dead` or `hung`), the crash exception repr with filesystem paths scrubbed to `<PATH>` (`null` for hangs), `heartbeat_age_s`, `tasks_failed`, `tasks_total`, and the poll index. |
| `freeze` | Freeze reason, source (`spot`), and the structured fault type. |
| `snapshot` | Snapshot ID, byte size, number of modules that serialized cleanly, names of any that errored, whether the bundle was encrypted, duration, and label. |
| `restart` | Attempt number, restart path (`light` or `heavy`), outcome (`recovered` or `failed`), latency, whether last-good state was restored, and the post-restart assessment. |
| `escalate` | Total attempts, the final snapshot ID, and the `halted` outcome. |

Every record from one fault window shares a generated `incident_id`, so a full recovery (from `detect` to `restart`) or an escalation (from `detect` to `escalate`) can be reconstructed.

The log is never cleared at boot. `escalation.json` and `state/cycle/control.json` are reset on every clean launch, while incident history accumulates across runs. Each line is encrypted at rest with AES-256-GCM when `[security.state_encryption]` is enabled, through the same key path as the rest of KAINE's persisted state. Operator filesystem paths are scrubbed from exception reprs, and no sensory content is recorded.

The incident log has no retention purge and no `retention_days` key, so its history is never deleted automatically.

The log is governed by `[spot.incident_log]`. The shipped config sets `[spot.incident_log].enabled = true`, so turning Spot on also turns on the log. Set `[spot.incident_log].enabled = false` to opt out.

### Research-log annotation

At each transition Spot also publishes a structured `spot.incident` bus event beside the live `spot.status` and `spot.log` events. When the curated research event log is enabled (`[research_event_log].enabled = true`; off in the shipped config), its observer writes each `spot.incident` event, filtered to the same operational fields as the durable log and stamped with the run's `run_id`, into `data/evaluation/research_events/` under the data root.

Run-level analysis can therefore see a freeze: the `incident_id` joins a record to the durable incident log, and the `run_id` joins it to the run. Each record carries Spot's `poll_index`, and the cycle's `tick_index` when it is available. No sensory content and no operator paths are included.

### Enabling and configuration

Enable Spot with `[spot].enabled = true` in `config/kaine.operator.toml`. All `[spot]` keys and defaults are documented in the [configuration reference](../appendix-a-configuration/core.md).

### Nexus indicators

The [Nexus](../05-nexus.md) diagnostics page (`/diagnostics/`) shows three Spot indicators:

- A pulsing border around the whole window, yellow while a recovery is in progress and red after an escalation, when the operator must act. With no fault there is no border.
- A text banner below the header with the state (`SPOT RECOVERY` or `SPOT CRITICAL`) and the affected module.
- The Spot console panel, a live log fed from the `spot.out` stream that shows each fault detection, restart attempt and outcome.
