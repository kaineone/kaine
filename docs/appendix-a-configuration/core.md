# Core, cycle and host

These settings configure the host, the Redis-backed event bus, the cognitive cycle, and the module enable gates. Change them when you move to new hardware, switch to unattended operation, tune the workspace tick, or turn modules on. They live in `config/kaine.toml` and are read at boot. For module-specific parameters see [Modules](../appendix-a-configuration/modules.md); for perception and sleep see [Perception feed and sleep](../appendix-a-configuration/perception-and-sleep.md); for lifecycle and research see [Lifecycle, evaluation and research](../appendix-a-configuration/lifecycle-and-research.md); for security and Nexus see [Security and Nexus](../appendix-a-configuration/security-and-nexus.md); for profiles and secrets see [Configuration overview](../appendix-a-configuration/README.md).

## Host connection and data

### Redis

Connection to the KAINE-owned Redis container in `compose/redis.yml`. KAINE uses its own Redis on port `6479` so it never touches a system Redis on `6379`. The bus loader reads Redis credentials from the shipped config or operator overrides; it ignores profiles and tiers.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Redis hostname. Change only when running Redis on a remote host. |
| `port` | integer | `6479` | KAINE Redis port. |
| `db` | integer | `0` | Redis logical database index. |
| `username` | string | absent | Redis ACL username, read from `kaine.toml` as a last resort. |
| `password` | string | absent | Redis ACL password, read from `kaine.toml` as a last resort. |

### Storage

Where growing data lives.

| Key | Type | Default | Description |
|---|---|---|---|
| `data_root` | string | absent | Root for all growing data. Relative paths resolve under it; absolute paths keep their value. Absent keeps everything relative to the working directory. `KAINE_DATA_ROOT` overrides this; containers set it to `/app`. |
| `min_free_gb` | number ≥ 0 | `20` | The pre-boot storage row fails when the data root's filesystem has less free space than this. |

On a compose install the first-run wizard writes `compose/kaine.storage.local.yml`, which binds KAINE's growing Docker volumes under the data root. It does so only when those volumes do not exist yet; otherwise it prints the commands to copy each existing volume first.

### Hardware

What KAINE may use on this host. The first-run wizard writes this section.

| Key | Type | Default | Description |
|---|---|---|---|
| `allowed_devices` | list of strings | absent | Devices modules may be placed on (`"cuda:N"`, `"xpu:N"`, `"mps"`, `"cpu"`). A module whose configured device is outside the set runs on the first allowed accelerator, or the CPU, with a warning. The CPU is always permitted. `KAINE_FORCE_DEVICE` overrides the set and is logged as doing so. If set, the list must not be empty (`kaine/config.py`). |
| `cpu_threads` | integer ≥ 1 | half the cores | Size of the torch CPU thread pool. |

#### `[hardware.devices]`

The device map: which device serves each role. The cycle's device keys, the compose GPU variables (`KAINE_ORGAN_GPU`, `KAINE_VISION_GPU` in `compose/.env`), and the native model server's GPU are all generated from it. The pre-boot "Device map" row fails when `compose/.env` or the cycle's device keys disagree with this map.

| Key | Type | Description |
|---|---|---|
| `organ` | string | The language organ's GPU. Voice-alignment training time-shares it. |
| `vision` | string | The vision encoder's GPU; in compose, also the cycle's and Chatterbox's card. |

### Tier and deployment

`[tier]` names a host tier and records which modules it disables and whether the oscillator layer is supported. `[deployment].tier` selects the tier.

`[tier]`

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | absent | Tier name. |
| `unsupported_modules` | list of strings | `[]` | Modules this tier disables. |
| `oscillator_supported` | boolean | `false` | Whether the oscillator layer is supported on this tier. |

`[deployment]`

| Key | Type | Default | Description |
|---|---|---|---|
| `tier` | string | absent | Tier to use. |

### Supporting services

`[services.<name>]` configures services KAINE uses but may not own: `model_server`, `chatterbox`, `speaches`.

| Key | Type | Default | Description |
|---|---|---|---|
| `shared` | bool | `false` | When `true`, KAINE never stops, restarts or reloads the service. `python -m kaine.setup.model_server stop` refuses, voice-alignment hot swap runs in `manual` mode, and the GPU pre-flight names the service instead of asking you to close it. |
| `process_names` | list of strings | service-specific | Process-name patterns that identify the service in the GPU pre-flight. Defaults are `llama-server`, `chatterbox`, and `speaches`. |

## Event bus

### Bus

Event bus tuning for Redis Streams.

| Key | Type | Default | Description |
|---|---|---|---|
| `default_maxlen` | integer | `100000` | Approximate per-stream cap. Redis trims with `MAXLEN ~` on every publish. |
| `audit_required` | boolean | `true` | When `true`, the bus refuses to start against an unauthenticated or externally-bound Redis. Set to `false` only for local development. |
| `max_connections` | integer | `1024` | Size of the shared connection pool for every module's blocking reads and publishes. |

### `[bus.per_stream_maxlen]`

Per-stream overrides. The key is the full stream name (`<module>.out` or `workspace.broadcast`). The shipped caps give observers and the research archive a long lookback, so a restart of several minutes loses no records. An unknown key logs a warning at pre-boot.

```toml
[bus.per_stream_maxlen]
"workspace.broadcast" = 100000
"topos.out" = 12000
"audition.out" = 12000
```

| Key | Type | Default | Description |
|---|---|---|---|
| `"workspace.broadcast"` | integer | `100000` | Cap for the broadcast stream (about 6.6 KB per entry). |
| `"topos.out"` | integer | `12000` | About 20 minutes at 10 Hz. Each entry carries a latent vector (about 40 KB), so this is the largest stream in memory. |
| `"audition.out"` | integer | `12000` | About 20 minutes at 10 Hz. |

The memory these caps imply must fit in Redis `maxmemory`, set per host with `KAINE_REDIS_MAXMEMORY` (default `4gb`; see [Containers](../07-deployment/containers.md)). The pre-boot `python -m kaine.preboot` reports it as the "Bus budget" row: for every stream the enabled modules produce, it multiplies the cap by a per-entry size, doubles the result for AOF-rewrite headroom, and compares it with `maxmemory`. The per-entry size is sampled from the running bus when possible, otherwise taken from the measured table in `kaine/bus/config.py`, otherwise estimated at 2 KB. The row FAILS only when the measured streams alone exceed `maxmemory`; when the overage depends on the 2 KB estimate it WARNS and names the estimated streams. It also WARNS above 70% of `maxmemory`. A full study with every module enabled needs `KAINE_REDIS_MAXMEMORY=12gb` or more on hosts with the RAM.

## Pre-boot checks

### Preboot

Disk-free rows of `python -m kaine.preboot`. KAINE never deletes memories, snapshots or research records to stay under a limit, so free disk is checked before boot. The check covers every configured durable path:

- `state_root` and `data_root`
- `[storage].data_root` and `[preboot].extra_disk_paths`
- `[lifecycle].snapshots_path`
- both `[preservation.*].out_root`
- `[evaluation].paths`
- `[research_event_log].log_dir` and its `raw_archive.archive_dir`
- `[hypnos.voice_alignment].adapter_output_dir` and `trainer_workdir`
- `[ignition_log].directory`
- `[spot.incident_log].path`
- the Eidolon self-model directory
- the native Redis data directory (`<state_root>/services/redis/data`, when it exists)

A path that does not exist yet is measured at its nearest existing parent. Paths on the same filesystem share one row. A row FAILS below the larger of `disk_fail_min_free_gb` and `disk_fail_min_free_percent` of its filesystem, and WARNS below `disk_warn_min_free_gb`. GB here is 2^30 bytes, as `df -h` reports.

| Key | Type | Default | Description |
|---|---|---|---|
| `state_root` | string | `"state"` | Entity state root (snapshots, memories, preserved beings). |
| `data_root` | string | `"data"` | Research data root (evaluation logs, trajectory, research events). |
| `disk_fail_min_free_gb` | float | `10.0` | Absolute free-space floor. |
| `disk_fail_min_free_percent` | float | `5.0` | Free-space floor as a percentage of the filesystem. |
| `disk_warn_min_free_gb` | float | `20.0` | Free space below which the row WARNS. |
| `extra_disk_paths` | list of strings | `[]` | Extra paths (relative to the working directory) for the pre-boot disk check, for example `["studies"]`. |

The same run also reports the "Bus budget" row described under [`[bus.per_stream_maxlen]`](#busper_stream_maxlen).

### GPU preflight

Cooperative pre-boot GPU headroom check. When enabled, the cycle verifies that each GPU has at least `min_free_vram_gb` free before any module initializes, so the entity is not OOM-killed mid-init. The model backend is a single-resident OpenAI-compatible server with no idle-model unload, so reclamation is report-only: the gate measures headroom and reports the server's resident model(s) and other GPU consumers, and never terminates a process. KAINE services (model server / Chatterbox / Speaches) are detected and preserved. If headroom is short the gate asks the operator to free memory and refuses to boot unless `KAINE_GPU_PREFLIGHT_APPROVED=1` is set. Unknown memory always passes with an annotation and never refuses boot.

Ships disabled — first boot is operator-supervised.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `min_free_vram_gb` | float | `2.0` | Minimum free VRAM (GB) required per GPU before any module initializes. |
| `model_server_url` | string | `"http://127.0.0.1:11434/v1"` | OpenAI-compatible model server, queried read-only via `/v1/models` to report what is resident. Same server Lingua uses. |
| `timeout_s` | float | `5.0` | HTTP timeout for the read-only preflight query. |
| `override_env` | string | `"KAINE_GPU_PREFLIGHT_APPROVED"` | Environment variable that bypasses a headroom failure when set to `1`. |

## Cycle timing and scoring

### Cycle

Cognitive cycle timing, read at startup.

| Key | Type | Default | Description |
|---|---|---|---|
| `processing_rate_hz` | float | `10.0` | Processing loop rate (100 ms/tick; alpha-band sampling / workspace tick). Independent of the experiential rate. |
| `experiential_rate_hz` | float | `3.333` | Rate at which a tick is promoted to a CONSCIOUS broadcast. This is the resting P3b conscious-access band, so the senses outrun awareness and several samples inform one conscious update. |
| `time_scale` | float | `1.0` | Global time dilation of the subjective clock. `1.0` = real-time. `0` freezes the entity. Values `> 1` run the mind faster than wall-clock as an aspirational target; slip is recorded honestly when the hardware cannot hold the rate. |
| `auto_time_scale` | bool | `false` | Enable automatic adjustment of `time_scale` to keep tick utilization near target. Disabled in deterministic mode. |
| `auto_time_scale_floor` | float | `0.1` | Minimum value `time_scale` is allowed to reach. |
| `auto_time_scale_target` | float | `0.85` | Target tick utilization (busy time / tick period). |
| `auto_time_scale_high` | float | `0.95` | Utilization above which the controller lowers `time_scale` after one dwell. |
| `auto_time_scale_low` | float | `0.6` | Utilization below which the controller raises `time_scale` after three dwells. Must be below `auto_time_scale_target`. |
| `auto_time_scale_dwell_s` | float | `10.0` | Minimum seconds a utilization condition must persist before `time_scale` changes; also the minimum time between changes. |
| `auto_time_scale_window_s` | float | `30.0` | Wall seconds over which tick busy-time is averaged as an exponential moving average. |
| `supervision_mode` | string | absent (operator) | `"operator"` or `"unattended"`. Absent means operator. `KAINE_CYCLE_UNATTENDED=1` takes precedence and conflicts with research mode or an operator-present signal. |

`time_scale = 0` with `auto_time_scale = true`, or an invalid threshold combination, refuses boot.

### Adaptive conscious access

`[cycle.access_rate]` adapts the conscious-access rate between the resting `experiential_rate_hz` and `processing_rate_hz`. See [The cognitive cycle](../08-cognitive-cycle/README.md) for how the rate is used.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Adapt the conscious-access rate. `false` gives the fixed resting rate. |
| `salience_floor` | float | `0.5` | Module reports at or below this salience do not raise access. Routine reports sit at or below it; alerts rise above it. |
| `phasic_decay_s` | float | `1.0` | Subjective seconds for a salient report's effect to decay by 1/e. |
| `baseline_arousal` | float | `[thymos].baseline_arousal` | Arousal at which the tonic drive is zero. Set only to override the Thymos baseline. |

Each tick the controller computes `drive = max(tonic, phasic)`, where `tonic` is Thymos arousal above baseline scaled to `[0, 1]` and `phasic` is the most salient module report above `salience_floor` scaled to `[0, 1]`, held as a peak that decays over `phasic_decay_s`. The access rate is then `experiential_rate_hz + (processing_rate_hz - experiential_rate_hz) * drive`.

### Syneidesis

Global Workspace scoring parameters.

| Key | Type | Default | Description |
|---|---|---|---|
| `top_k` | integer | `5` | Maximum coalition size: the top-*k* scoring events are broadcast each tick. |
| `publication_threshold` | float | `0.35` | Minimum salience for an event to enter the coalition. Below this the tick publishes executive inhibition. |
| `novelty_window` | integer | `32` | Sliding-window length (ticks) for the novelty detector. |
| `salience_thymos_factor` | string | `"state_modulator"` | Source of the Thymos salience factor. `"state_modulator"` wires the real arousal-weighted StateModulator. `"static"` bypasses affect weighting and fires a degraded-mode warning. |
| `salience_goal_factor` | string | `"static"` | Source of the goal salience factor. `"static"` leaves the goal factor at a constant; this is the shipped default and logs at INFO. `"drive_relevance"` is built and selectable but ships off by default: it changes what reaches the workspace and would shift the research baseline. |
| `precision_weighting` | boolean | `true` | Weight each candidate by its source's precision (inverse variance of the intensities it publishes) relative to the other sources. |
| `precision_sample_weight` | float | `0.02` | Exponential-average weight per event for the precision statistics (about 50 events). |
| `precision_warmup_samples` | integer | `20` | Events a source needs before it counts as warmed; weights stay 1.0 until three sources are warmed. |
| `precision_bounds` | array of 2 floats | `[0.5, 1.5]` | Lower and upper bounds on a source's precision weight. |
| `arousal_contrast_gain` | float | `8.0` | Logistic contrast slope at arousal 1.0; the slope is 0 at or below baseline arousal. `0` disables the contrast. |

### Volition

Executive action selection (`kaine/workspace/volition.py`). When the section is absent, Volition falls back to `DriveBiasedActionSelectionPolicy`.

| Key | Type | Default | Description |
|---|---|---|---|
| `policy` | string | `""` (unset) | `"self_initiated_report"` selects `SelfInitiatedReportPolicy`: the entity speaks or thinks only from its own precision-weighted surprise, never from a user utterance. Any other value or omission uses the drive-biased or plain default policy. |
| `drive_initiative` | boolean | `true` | Consulted whenever `policy` is not `"self_initiated_report"`. `true` injects drive threshold-crossings as intents; `false` falls back to the plain default policy. |
| `report_threshold` | float | `0.6` | Coalition surprise at or above this speaks aloud (`intent.speak`). The code only enforces `0 <= think_threshold <= report_threshold <= 1`; setting it at or above `publication_threshold` is a recommendation, not a requirement. |
| `think_threshold` | float | `0.45` | Coalition surprise at or above this (but below `report_threshold`) forms an internal `intent.think`. |
| `speak_refractory_s` | float | `8.0` | Minimum seconds between spoken reports under the self-initiated policy. `NousProposalSource` also reads this when Nous is enabled. |
| `think_refractory_s` | float | `3.0` | Minimum seconds between internal think intents under the self-initiated policy. `NousProposalSource` also reads this when Nous is enabled. |
| `interrupt_threshold` | float | unset | Opt-in mid-utterance interruption. Must satisfy `report_threshold < interrupt_threshold <= 1.0`. |
| `sig_expiry_s` | float | unset | Expiry for the coarse novelty signature. Unset means it never expires. |

With the base profile selected, `policy` is `"self_initiated_report"`, `drive_initiative` is `false`, and `sig_expiry_s` is `300.0`.

Regardless of policy, inhibition gates first: if `snapshot.inhibited` is true, `Volition.select()` returns no intents.

### Oscillator

Oscillatory-binding layer. Each module maintains a spiking LIF population; Syneidesis uses pairwise phase-locking value among a coalition's source modules to apply a bounded coherence multiplier to aggregate salience.

Ships disabled; when `enabled = false` the multiplier is exactly `1.0`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `population_size` | integer | `16` | LIF neuron population size per module. Minimum 16 enforced at boot. |
| `plv_window` | integer | `10` | Sliding-window length (ticks) for PLV computation. Minimum 10 enforced at boot. |
| `coherence_floor` | float | `0.8` | Lower bound for the coherence multiplier. Must be `<= coherence_ceiling`. |
| `coherence_ceiling` | float | `1.25` | Upper bound for the coherence multiplier. |
| `beta` | float | `0.9` | LIF membrane decay coefficient. |
| `threshold` | float | `1.0` | LIF firing threshold. |
| `base_drive` | float | `1.5` | Scales per-tick input current built from module activity. |

Requires the `[oscillator]` extra (`snntorch` + `scipy`). When the extra is absent and the layer is enabled, modules report a neutral phase and the factor degrades to `1.0`.

## Experiment settings

Per-run identity, seeding, and manifest for research reproducibility.

| Key | Type | Default | Description |
|---|---|---|---|
| `seed` | integer or `""` | `""` | Fixed integer makes a run reproducible. Blank generates a fresh seed each boot. The manifest always records the seed used, so even an unseeded run can be reproduced after the fact. |
| `write_manifest` | boolean | `true` | Write the run manifest to `data/evaluation/runs/<run_id>/manifest.json` at boot. The manifest holds only run id, seed, git sha, model ids, a config digest, started-at, and the KAINE version — no entity interior, no operator-identifying data. |
| `deterministic` | boolean | `false` | Opt-in deterministic cycle mode. Event timestamps come from a logical clock and each tick's events are ordered by a canonical key, so two runs with the same seed and the same input produce an identical cognitive trajectory. Wall-clock latency measurements remain physical. Off in production; used by the controlled oscillatory-ablation runner (see [Running experiments](../15-experiments/README.md)). |

Determinism holds for the seeded procedural feed. Under `[perception_feed].mode = "playlist"` the stimulus is paced by the real wall clock, so playlist runs are reproducible by per-item sha256, not bit-for-bit.

## Logging

`[logging]` sets the cycle's log level.

| Key | Type | Default | Description |
|---|---|---|---|
| `level` | string | `"INFO"` | Root log level for `python -m kaine.cycle`: `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (case-insensitive). Any other value refuses boot. |

## Remote operation

### Remote bridge

Remote perception bridge — a WebSocket server that runs in the cycle process and gives the operator direct access to Topos, Audition, and Vox. It lets the operator stream a remote camera into vision, a remote microphone into hearing, and receive generated speech plus the conversation transcript over a Tailscale tailnet. Ships disabled.

Remote payloads are decoded in memory and never written to disk. Remote audio uses the same VAD/utterance pipeline as the physical mic and is attributed `source_label = "remote"` so it never impersonates the physical microphone. While a remote camera or mic is connected, `claim_senses = true` marks the matching physical sense as not-desired and restores the previous state on disconnect.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `host` | string | `"127.0.0.1"` | Bind address. Point at the host's Tailscale interface for remote operation; never `0.0.0.0` on a public NIC. |
| `port` | integer | `8089` | WebSocket port for all channels. |
| `token` | string | `""` | Optional shared secret. Empty means the tailnet ACL is the only boundary. Non-loopback binds require a token. |
| `video_max_fps` | float | `4.0` | Latest-wins ceiling for remote frames handed to Topos. |
| `audio_sample_rate` | integer | `16000` | Remote PCM format (int16 mono). |
| `audio_vad_backend` | string | `"webrtcvad"` | Utterance segmentation for remote audio. `"webrtcvad"` needs the `[audio]` extra; `"rms"` is the dependency-free fallback. |
| `claim_senses` | boolean | `true` | While a remote camera/mic is connected, mark the matching physical sense as not-desired. |
| `speech_queue_size` | integer | `8` | Per-client outbound speech queue. Oldest clips drop when a slow client falls behind. |
| `allowed_origins` | list of strings | `["null", "http://127.0.0.1:17893", "https://appassets.androidplatform.net"] | Browser WebSocket Origin allowlist. `"null"` admits native clients that send no Origin header. |
| `max_message_bytes` | integer | `2097152` | Hard cap on a single inbound WebSocket message in bytes. |
| `ssl_certfile` | string | `""` | Optional TLS certificate PEM file. Set both this and `ssl_keyfile` to serve over `wss` instead of `ws`. |
| `ssl_keyfile` | string | `""` | Optional TLS key PEM file. |

Security: clients must present `token` as `Authorization: Bearer <token>`; query-string and `Sec-WebSocket-Protocol` tokens are rejected. A non-loopback bind without a token refuses to start. The default port is `8089`, the same default as `[perception_preview]`; change one if you enable both.

## Module enable gates

`[modules]` holds per-module enable flags. The committed `config/kaine.toml` ships every flag as `false`; enabling a module is a local-only edit. For what each module does, see [The modules](../09-modules/README.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `echo` | boolean | `false` | Permanent test infrastructure. Never enable in production. |
| `soma` | boolean | `false` | Predictive interoception. |
| `chronos` | boolean | `false` | Temporal awareness and event-rhythm prediction. |
| `topos` | boolean | `false` | Vision encoder and live camera. |
| `nous` | boolean | `false` | Active inference engine. |
| `mnemos` | boolean | `false` | Vector-store memory. |
| `eidolon` | boolean | `false` | Self-model. |
| `thymos` | boolean | `false` | Affect, drives, and affect coupling. |
| `praxis` | boolean | `false` | Bounded effectors. |
| `lingua` | boolean | `false` | Language organ. |
| `vox` | boolean | `false` | Voice synthesis. |
| `audition` | boolean | `false` | Hearing. |
| `hypnos` | boolean | `false` | Offline consolidation. |
| `empatheia` | boolean | `false` | Social cognition. |
| `phantasia` | boolean | `false` | World model. |
| `perception` | boolean | `false` | Perception locus arbiter (physical-XOR-virtual sense gating). |
| `mundus` | boolean | `false` | Embodiment control plane. The continuous control surface is built but inert at runtime; nothing drives its per-tick loop yet. Also requires `KAINE_MUNDUS_OPERATOR_APPROVED=1`. |

The guard test that enforces the all-off invariant is `tests/test_boot_wiring.py::test_committed_config_ships_all_modules_disabled`.

With no profile selected, the loader applies the base-thesis `thesis_test` profile, which turns `soma`, `chronos`, `topos`, `audition`, `lingua`, and `thymos` on and leaves the rest off. The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](README.md#module-defaults)).

## Plugins

`[plugins]` loads plugin modules. `enabled` lists the plugin names to load; each loaded plugin can have its own `[plugins.<name>]` table.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | list of strings | `[]` | Names of plugins to load. |

Per-plugin settings live under `[plugins.<name>]`. Their keys are plugin-specific.

## Spot supervisor

`[spot]` configures the module supervisor (watchdog). Spot runs in the cycle process, polls every module for crash or hang, and on a fault freezes the cycle, snapshots last-good state, and restarts the faulted module. After `max_restart_attempts` consecutive failures it saves a final snapshot, shuts every module down, writes `state/cycle/escalation.json`, and exits non-zero. Spot never reboots the host.

Ships disabled — first boot is operator-supervised. For remote operation guidance see [Remote operation and the Spot supervisor](../06-operation/remote-and-spot.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `poll_interval_s` | float | `2.0` | Seconds between liveness polls. |
| `heartbeat_timeout_s` | float | `60.0` | A module is hung only if its heartbeat is older than this, a task is still running, and the entity is not sleeping. |
| `max_restart_attempts` | integer | `5` | Maximum consecutive restart attempts before escalation. |
| `restart_backoff_s` | float | `3.0` | Seconds between restart attempts. |
| `selftest_timeout_s` | float | `10.0` | Bound on Spot's scratch freeze/restart self-test. |

### `[spot.per_module_timeout_s]`

Optional per-module heartbeat timeout overrides. The key is the module name; the value overrides `heartbeat_timeout_s` for that module only.

```toml
[spot.per_module_timeout_s]
lingua = 120.0
```

### `[spot.incident_log]`

Durable, append-only record of Spot's fault-recovery lifecycle. Spot writes one encrypted JSONL line per transition under `path`, all sharing a generated `incident_id`. The log is never cleared at boot, so crash/recovery evidence accumulates across runs. It is encrypted at rest when state encryption is on, and filesystem paths are scrubbed from exception reprs before write. Retention auto-purge is unconditionally disabled.

Ships `enabled = true`, but the block is dormant while `[spot].enabled = false`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Whether Spot writes the durable incident log. |
| `path` | string | `"state/cycle/incidents"` | Directory for the daily-rotated incident files. |
