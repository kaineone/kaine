# Remote operation and the Spot supervisor

Use this page to operate KAINE from another device over a tailnet, or to turn on automatic module supervision. It covers the remote perception bridge and Spot, the cycle-layer watchdog that detects and recovers from module faults.

## Remote perception bridge

The remote perception bridge is [`kaine/remote/bridge.py`](../../kaine/remote/bridge.py). It is a WebSocket server that runs inside the cycle process so it can reach [Topos](../09-modules/topos.md), [Audition](../09-modules/audition.md), and [Vox](../09-modules/vox.md) directly. No external process has that access.

The shipped config disables the bridge by default: `[remote_bridge].enabled = false`. Enable it in `config/kaine.operator.toml`.

### Channels

The bridge listens on one port, `[remote_bridge].port` (default `8089`), with separate paths for each direction:

| Path | Direction | Payload |
|---|---|---|
| `/ingest/video` | client → entity | Binary JPEG or PNG frames. The bridge converts each frame to an in-memory `PIL.Image` and passes it to `Topos.process_frame()`. Only the latest frame is kept, capped at `video_max_fps`. |
| `/ingest/audio` | client → entity | Binary int16 mono PCM at `audio_sample_rate`. It goes through the same VAD/utterance pipeline as the physical microphone, then to `Audition.process_audio(..., source_label="remote")`. |
| `/speech` | entity → client | Binary WAV clips tapped from Vox playback. Local playback continues. |
| `/transcript` | entity → client | JSON lines: `{role: "entity"\|"heard", text, type, source_label, ts}`. |

While a remote camera or microphone is connected and `claim_senses` is true, the matching physical sense is marked not-desired through `perception_state`. The physical sensor is restored when the remote client disconnects.

### Security and privacy

- Bind to the tailnet. Set `[remote_bridge].host` to the host's Tailscale address (`100.x.y.z`). Never use `0.0.0.0` on a public NIC. The tailnet ACL is the security boundary.
- Use a token. Set `[remote_bridge].token` for defense in depth. Clients must send it as `Authorization: Bearer <token>`. Query-string and `Sec-WebSocket-Protocol` tokens are rejected so the secret does not end up in logs or browser history. Without a token, the bridge refuses to bind a non-loopback host.
- Zero persistence. Remote frames, PCM, and tapped speech live only in memory. The bridge writes nothing to disk. This is covered by [`tests/test_remote_bridge.py`](../../tests/test_remote_bridge.py).
- Secure contexts for browsers. Browsers require HTTPS to access camera and microphone. The simplest setup is `tailscale serve`, which gives the host a real certificate on its `ts.net` name and reverse-proxies WebSocket upgrades to the locally-bound bridge.

The operator client apps — the phone or laptop PWA and the playlist feeder — are in a separate private repo. The bridge is only the entity-side endpoint they connect to.

### Operator presence

A non-research boot with an operator present is operator-supervised. A non-research boot without an operator uses the unattended gate at `kaine/cycle/unattended_gate.py`. Whether supervising through the remote panel and live audio/video counts as "operator present" is for the operator to decide explicitly. The bridge does not change any boot gate: not the operator-present gate, not the unattended gate, and not the autonomous safety-net gate used in research mode.

## Module supervisor (Spot)

Spot is the cycle-layer watchdog at [`kaine/cycle/spot.py`](../../kaine/cycle/spot.py). It is not a registry module. It polls every module for liveness every `[spot].poll_interval_s` seconds (default `2`).

The shipped config disables Spot by default: `[spot].enabled = false`. Enable it in `config/kaine.operator.toml`.

### Liveness model

Spot distinguishes two fault modes:

- **Crash (dead):** a module task exited with an exception, or returned while the module was not shutting down cleanly.
- **Hang:** a module's heartbeat is older than `[spot].heartbeat_timeout_s` (default `60` s), a task is still running, *and* the entity is not in a [Hypnos](../09-modules/hypnos.md) sleep pass. All three conditions must hold.

Spot handles one fault per poll.

Spot skips assessment entirely while the cycle is frozen by an operator or welfare freeze, or by any mixed stack containing one. A frozen cycle is left alone until the freeze is cleared.

### Freeze and restart ladder

Spot only runs this ladder when it detects a fault in an unfrozen cycle. On a fault, it immediately freezes the cycle with `source="spot"` and snapshots last-good state. It then tries to recover:

1. **Light restart.** Call `BaseModule.restart()` for pure modules with no external resource handles.
2. **Heavy rebuild.** For modules holding external resources: shut down the old instance, build a fresh one through the injected factory, re-initialize it, replace it in the registry, rewire subscriptions, and restore the last-good snapshot.

Between attempts, Spot waits `[spot].restart_backoff_s` seconds. If recovery succeeds, the cycle unfreezes. If the same module fails again, the attempt counter increments.

### Escalation

After `[spot].max_restart_attempts` consecutive failures (default `5`):

1. Take a final state snapshot.
2. Shut down every module.
3. Write `state/cycle/escalation.json` under `KAINE_DATA_ROOT` with the module name, attempt count, snapshot ID, and a reboot instruction.
4. Publish a `CRITICAL spot.status` event on the bus.
5. Exit the entrypoint with a non-zero status.

Spot never reboots the host. The operator must reboot the machine and restart the cycle manually. The `escalation.json` file records the snapshot to restore from.

### Durable incident log

Spot writes an append-only log of its fault-recovery work to `state/cycle/incidents/incidents-<UTC-date>.jsonl` under `KAINE_DATA_ROOT`. This is separate from the live `spot.out` bus events that Nexus shows; bus events are trimmed on every publish, but the incident log is kept on disk. The log supports research, operator post-mortems, and welfare review.

Each lifecycle transition produces one record:

| Transition | What is recorded |
|---|---|
| `detect` | Fault class (`dead` or `hung`), the crash exception repr with filesystem paths scrubbed to `<PATH>` (`null` for hangs), `heartbeat_age_s`, `tasks_failed`, `tasks_total`, and the poll index. |
| `freeze` | Freeze reason, source (`spot`), and the structured fault type. |
| `snapshot` | Snapshot ID, byte size, number of modules that serialized cleanly, names of any that errored, whether the bundle was encrypted, duration, and label. |
| `restart` | Attempt number, restart path (`light` or `heavy`), outcome (`recovered` or `failed`), latency, whether last-good state was restored, and the post-restart assessment. |
| `escalate` | Total attempts, the final snapshot ID, and the `halted` outcome. |

Every record from a single fault window shares the same generated `incident_id`, so a full recovery (`detect` → ... → `restart`) or escalation (`detect` → ... → `escalate`) can be reconstructed.

The log is never cleared at boot. This is deliberate: `escalation.json` and `state/cycle/control.json` are reset on every clean launch, but incident history accumulates across runs. Each line is AES-256-GCM encrypted at rest when `[security.state_encryption]` is enabled, using the same key path as the rest of KAINE's persisted state. Operator filesystem paths are scrubbed from exception reprs, and no sensory content is recorded.

Retention auto-purge is unconditionally disabled for the incident log. There is no `retention_days` key, so research history is never deleted automatically.

The log is governed by `[spot.incident_log]`. The shipped config sets `[spot.incident_log].enabled = true`, so turning Spot on also turns on the log. Set `[spot.incident_log].enabled = false` to opt out.

### Research-log annotation

At each transition Spot also publishes a structured `spot.incident` bus event alongside the live `spot.status` and `spot.log` events. When the curated research event log is enabled (`[research_event_log].enabled = true`), its observer captures each `spot.incident` event — privacy-filtered to the same operational fields as the durable log — into `data/evaluation/research_events/` under `KAINE_DATA_ROOT`. The record is stamped with the run's `run_id`.

A freeze becomes visible to run-level analysis because a record carries the `incident_id` (joining it to the durable incident log) and the `run_id` (joining it to the run). It always includes Spot's `poll_index`, plus the cycle `tick_index` when available. No sensory content and no operator paths are included.

### Enabling and configuration

Enable Spot with `[spot].enabled = true` in `config/kaine.operator.toml`. All `[spot]` keys and defaults are documented in the [configuration reference](../appendix-a-configuration/core.md).

### Nexus indicators

The [Nexus](../05-nexus.md) diagnostics page (`/diagnostics/`) shows three Spot indicators:

- **Alert border.** A full-window pulsing border: yellow means recovery is in progress; red means escalation and operator action is required; no border means nominal.
- **Spot banner.** A text banner below the header showing the state (`SPOT RECOVERY` or `SPOT CRITICAL`) and the affected module name.
- **Spot console panel.** A live incident log fed from the `spot.out` bus stream, showing each fault detection, restart attempt, and outcome.
