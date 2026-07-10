# KAINE Configuration Reference

This document is the authoritative reference for `config/kaine.toml` and the companion `config/secrets.toml`. Every section and every key is listed here with its type, shipped default, and purpose. All defaults are the values present in the committed file; local overrides are never committed.

---

## How configuration works

**Two-file split.** `config/kaine.toml` is committed and contains no secrets. `config/secrets.toml` is gitignored and holds credentials (see [Secrets file](#secrets-file-configsecretstoml) below). Environment variables override the secrets file, which overrides `kaine.toml`.

**All modules off by default.** The committed `kaine.toml` ships with every module toggle set to `false`. Enabling modules is a *local* edit that is never committed. The guard test `test_committed_config_ships_all_modules_disabled` asserts this invariant on every CI run.

**Optional dependency extras.** Several features require installing Python package extras alongside the base install:

| Extra flag | Command | Enables |
|---|---|---|
| `[audio]` | `pip install -e .[audio]` | Live microphone capture (`sounddevice`, `webrtcvad`, `funasr`, `librosa`) |
| `[vision]` | `pip install -e .[vision]` | Live camera capture (`opencv-python-headless`) |
| `[reasoning]` | `pip install -e .[reasoning]` | Active inference engine for Nous (`inferactively-pymdp`, `jax[cpu]`) |
| `[worldmodel]` | `pip install -e .[worldmodel]` | DreamerV3 RSSM world model for Phantasia (`jax[cpu]`, `chex`, `einops`) |
| `[oscillator]` | `pip install -e .[oscillator]` | Oscillatory binding layer (`snntorch`, `scipy`) |
| `[training]` | `pip install -e .[training]` | Voice alignment DPO/QLoRA training (`unsloth`, `trl`, `peft`, `datasets`) |

**Unknown keys are fatal at boot.** Every module factory validates its config section against an explicit allowlist. A typo in a key name raises `ValueError` before any module starts.

---

## `[redis]`

Connection to the KAINE-owned Redis container (`compose/redis.yml`). KAINE uses a dedicated Redis on port 6479 so it never conflicts with a system Redis on 6379.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Redis hostname. Change only if running Redis on a remote host (not recommended). |
| `port` | integer | `6479` | Redis port. Matches the KAINE compose stack; deliberately not 6379. |
| `db` | integer | `0` | Redis logical database index. |

---

## `[bus]`

Event bus tuning parameters. The bus is Redis Streams; these control stream retention.

| Key | Type | Default | Description |
|---|---|---|---|
| `default_maxlen` | integer | `100000` | Approximate per-stream cap. Redis trims with `MAXLEN ~` on every publish. |
| `audit_required` | boolean | `true` | When true the bus refuses to start against an unauthenticated or externally-bound Redis. Set to `false` only for local development. |

### `[bus.per_stream_maxlen]`

Per-stream overrides. The key is the full stream name (`<module>.out` or `workspace.broadcast`). Example:

```toml
[bus.per_stream_maxlen]
"workspace.broadcast" = 50000
```

| Key | Type | Default | Description |
|---|---|---|---|
| `"workspace.broadcast"` | integer | `50000` | Lower cap for the broadcast stream (workspace snapshots are larger than module events). |

---

## `[spot]`

Module supervisor (watchdog). A cycle-layer component — not a registry module — that runs alongside the cognitive cycle. On each poll Spot assesses every module for crash or hang. On a fault it freezes the cycle (with `source="spot"`), snapshots last-good state, and works through a restart ladder. After `max_restart_attempts` consecutive failures it saves a final snapshot, shuts every module down, writes `state/cycle/escalation.json`, and signals the entrypoint to exit non-zero. Spot never reboots the host; it asks the operator to do so.

Ships disabled. First boot is operator-supervised; enable after you are comfortable with the supervised cycle.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `poll_interval_s` | float | `2.0` | Seconds between liveness polls. |
| `heartbeat_timeout_s` | float | `60.0` | A module is considered hung only if its heartbeat is older than this *and* a task is still running *and* the entity is not sleeping. Deliberately generous to avoid false positives on slow ticks or Hypnos passes. |
| `max_restart_attempts` | integer | `5` | Maximum consecutive restart attempts before escalation. |
| `restart_backoff_s` | float | `3.0` | Seconds Spot waits between restart attempts. |

### `[spot.per_module_timeout_s]`

Optional per-module heartbeat timeout overrides. The key is the module name; the value is the timeout in seconds. Overrides `heartbeat_timeout_s` for that module only. Example:

```toml
[spot.per_module_timeout_s]
lingua = 120.0
```

| Key | Type | Description |
|---|---|---|
| `<module_name>` | float | Per-module heartbeat timeout (seconds). Overrides `heartbeat_timeout_s` for that module. |

### `[spot.incident_log]`

Durable, append-only record of Spot's fault-recovery lifecycle. Spot writes one JSONL record per transition (detect, freeze, snapshot, restart, escalate) under `path`, all sharing a generated `incident_id`. Unlike `escalation.json` / `control.json` (single-state, wiped on every clean boot), this log is **never cleared at boot**, so crash/recovery evidence accumulates across runs for research and post-mortem review. Each line is encrypted at rest when `[security.state_encryption]` is enabled, and operator filesystem paths are scrubbed from exception reprs before write. Retention auto-purge is unconditionally disabled (there is deliberately no `retention_days` key) — research history is never auto-deleted. See [Operations → Durable incident log](operations.md#durable-incident-log).

Ships `enabled = true`, but the whole block is dormant while `[spot].enabled = false` (the shipped first-boot default): any operator who turns Spot on gets the log automatically.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Whether Spot writes the durable incident log. Dormant until `[spot].enabled = true`. |
| `path` | string | `"state/cycle/incidents"` | Directory for the daily-rotated `incidents-<UTC-date>.jsonl` files. |

---

## `[gpu_preflight]`

Cooperative pre-boot GPU headroom check. When enabled, the cycle verifies each GPU has at least `min_free_vram_gb` free BEFORE any module initializes, so the entity is not OOM-killed mid-init (which Spot would then thrash on). The model backend is a single-resident OpenAI-compatible server (Unsloth Studio / llama.cpp) with no idle-model unload, so reclamation is report-only: the gate measures headroom and reports the server's resident model(s) and other GPU consumers, and never terminates a process — KAINE services (model server / Chatterbox / Speaches) are detected and preserved. If headroom is short it asks the operator to free memory and refuses to boot unless `KAINE_GPU_PREFLIGHT_APPROVED=1` is set.

Ships disabled — first boot is operator-supervised.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `min_free_vram_gb` | float | `2.0` | Minimum free VRAM (GB) required per GPU before any module initializes. |
| `model_server_url` | string | `"http://127.0.0.1:11434/v1"` | OpenAI-compatible model server, queried read-only (`/v1/models`) to report what is resident. Same server Lingua uses. |
| `timeout_s` | float | `5.0` | HTTP timeout for the read-only preflight query (seconds). |

---

## `[remote_bridge]`

Remote perception bridge — a cycle-layer WebSocket server (like Spot, not a registry module) that lets the operator stream a remote camera into the entity's vision (`Topos.process_frame`), a remote microphone into its hearing (through the same `LiveMicrophone` VAD/utterance pipeline as the physical mic, attributed `source_label = "remote"`), and receive generated speech (a composed Vox playback tap) plus the conversation transcript (`lingua.external` / `audition.out`) — over the operator's Tailscale tailnet. Ships disabled. Remote payloads are decoded in memory and never written to disk (zero-raw-sense-data persistence holds). Path-routed channels on one port: `/ingest/video`, `/ingest/audio`, `/speech`, `/transcript`.

Security: the tailnet ACL is the boundary — set `host` to the host's Tailscale interface address, never `0.0.0.0` on a public NIC. `token`, when set, must be presented by clients (`?token=…` or `Authorization: Bearer …`) or the connection is closed at handshake.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled; the cycle starts no bridge when false. |
| `host` | string | `"127.0.0.1"` | Bind address. Point at the tailnet interface for remote operation. |
| `port` | integer | `8089` | WebSocket port for all four channels. |
| `token` | string | `""` | Optional shared secret. Empty = tailnet ACL only. |
| `video_max_fps` | float | `4.0` | Latest-wins ceiling for remote frames handed to Topos; excess frames are dropped and counted. |
| `audio_sample_rate` | integer | `16000` | Remote PCM format (int16 mono). |
| `audio_vad_backend` | string | `"webrtcvad"` | Utterance segmentation for remote audio — same pipeline as the physical mic. `"rms"` is the dependency-free fallback. |
| `claim_senses` | boolean | `true` | While a remote camera/mic is connected, mark the matching physical sense not-desired (`perception_state`) so the two never fight; the prior desired state is restored on disconnect. |
| `speech_queue_size` | integer | `8` | Per-client outbound speech queue (clips). Oldest dropped when a slow client falls behind. |

---

## `[cycle]`

Cognitive cycle timing, read at startup.

| Key | Type | Default | Description |
|---|---|---|---|
| `processing_rate_hz` | float | `10.0` | Processing loop rate (100 ms/tick; alpha-band sampling / workspace tick). Benchmarked-cleared on this host (RTX 4070 SUPER, ~17 Hz tick headroom). Independent of the experiential rate. |
| `experiential_rate_hz` | float | `3.333` | Rate at which a tick is promoted to a CONSCIOUS broadcast. Held at the resting P3b conscious-access band (~3.33 Hz) so the senses (e.g. 10 Hz vision) genuinely outrun awareness and several samples inform one conscious update. In organic brains this rate is state-variable (arousal / fight-flight raises it); modelling that variability (e.g. arousal-modulated via Thymos + `time_scale`) is deliberate future work — a fixed resting baseline is used now. |
| `time_scale` | float | `1.0` | Global time dilation of the entity's subjective clock. `1.0` = real-time (the shipped default — behavior is byte-identical to no clock at all). `0` freezes the entity (the subjective clock stops; reuses the existing freeze/suspend path). Values `> 1` run the mind faster than wall-clock as an aspirational target: the cycle attempts the faster tick rate and, when the hardware cannot hold it, the existing slip measurement records the overrun honestly. One knob dilates the whole mind coherently because every cognitive timer reads the shared EntityClock. |

---

## `[experiment]`

Per-run identity, seeding, and manifest (research reproducibility). At boot the cycle pins the global RNGs from `seed`, mints a unique run id, and stamps that id plus a per-stream sequence number onto every durable record, so a dataset can be grouped by run and a missing record detected.

| Key | Type | Default | Description |
|---|---|---|---|
| `seed` | integer or `""` | `""` | Fixed integer makes a run reproducible. Blank (`""`) generates a fresh seed each boot — the manifest always records whatever seed was used, so even an unseeded run can be reproduced after the fact. |
| `write_manifest` | boolean | `true` | Write the run manifest to `data/evaluation/runs/<run_id>/manifest.json` at boot. Holds only run id, seed, git sha, model ids, a config digest, started-at, and the kaine version — no entity interior, no operator-identifying data (export-eligible). |
| `deterministic` | boolean | `false` | Opt-in deterministic cycle mode. When true, event timestamps come from a logical clock (base epoch + `tick_index * tick_period`) and each tick's events are ordered by a canonical key, so two runs with the same seed and the same input produce an identical cognitive trajectory (selected coalitions, salience scores, inhibition, volition decisions, logical timestamps). Does NOT make wall-clock latency reproducible (`wall_duration_ms` / `slip_ms` remain physical measurements). Off in production (real wall-clock time); used by the controlled oscillatory-ablation runner. |

---

## `[syneidesis]`

Global Workspace scoring parameters.

| Key | Type | Default | Description |
|---|---|---|---|
| `top_k` | integer | `5` | Maximum coalition size: the top-*k* scoring events are broadcast each tick. |
| `publication_threshold` | float | `0.35` | Minimum salience for an event to enter the coalition. Below this the tick publishes executive inhibition. |
| `novelty_window` | integer | `32` | Sliding-window length (ticks) for the novelty detector. Events seen too frequently get a novelty penalty. |

---

## `[oscillator]`

Oscillatory-binding layer (paper §3.2). Each module maintains a spiking LIF population; Syneidesis uses pairwise phase-locking value (PLV) among a coalition's source modules to apply a bounded coherence multiplier to aggregate salience. Ships disabled; when `enabled = false` the multiplier is exactly 1.0 and workspace selection is bit-for-bit the pre-layer behavior.

Requires the `[oscillator]` extra (`snntorch` + `scipy`). When the extra is absent and the layer is enabled, modules report a neutral phase and the coherence factor degrades gracefully to 1.0.

The paper flags this layer as empirically uncharacterized. Enable only after the sidecar coherence observer has measured its effect.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `population_size` | integer | `16` | LIF neuron population size per module. Minimum 16 enforced at boot. |
| `plv_window` | integer | `10` | Sliding-window length (ticks) for PLV computation. Minimum 10 enforced at boot. |
| `coherence_floor` | float | `0.8` | Lower bound for the coherence multiplier. Attenuates desynchronized coalitions. Must be `<= coherence_ceiling`. |
| `coherence_ceiling` | float | `1.25` | Upper bound for the coherence multiplier. Boosts phase-locked coalitions. |
| `beta` | float | `0.9` | LIF membrane decay coefficient. |
| `threshold` | float | `1.0` | LIF firing threshold. |
| `base_drive` | float | `1.5` | Scales per-tick input current built from module activity. |

---

## `[modules]`

Per-module enable flags. All ship as `false`. Enabling a module is a local-only edit; the committed file is always all-off. The `echo` module is permanent test infrastructure and must stay disabled in production.

| Key | Type | Shipped default | Description |
|---|---|---|---|
| `echo` | boolean | `false` | EchoModule — test infrastructure only. Never enable in production. |
| `soma` | boolean | `false` | Predictive interoception (substrate monitoring, fatigue, homeostatic regulation). |
| `chronos` | boolean | `false` | Temporal awareness and event-rhythm prediction. |
| `topos` | boolean | `false` | Vision encoder (DINOv2-small) and live camera. |
| `nous` | boolean | `false` | Active inference engine (pymdp/JAX). Requires `[reasoning]` extra. |
| `mnemos` | boolean | `false` | Vector-store memory (Qdrant). |
| `eidolon` | boolean | `false` | Self-model: values, norms, personality baseline, capability map. |
| `thymos` | boolean | `false` | Affect (VAD dimensional state), drives, and affect coupling. |
| `praxis` | boolean | `false` | Bounded effectors: file sandbox, notifications, shell whitelist. |
| `lingua` | boolean | `false` | Language organ: conditioned generation via a local OpenAI-compatible model server. |
| `vox` | boolean | `false` | Voice synthesis (Chatterbox TTS) with prosodic mirroring. |
| `audition` | boolean | `false` | Hearing: STT via Speaches, vocal-emotion via emotion2vec+. |
| `hypnos` | boolean | `false` | Offline consolidation: replay, downscaling, voice alignment. Constructed in a second pass after Mnemos/Nous/Thymos/Phantasia. |
| `empatheia` | boolean | `false` | Social cognition / theory of mind, agent profiling. |
| `phantasia` | boolean | `false` | World model (DreamerV3 RSSM core). Requires `[worldmodel]` extra for the real backend. |
| `perception` | boolean | `false` | Embodiment helper: perception locus arbiter (physical-XOR-virtual sense gating). |
| `mundus` | boolean | `false` | Embodiment control plane: routes perception/action to a body through a pluggable adapter (`[mundus].adapter`). Additionally requires the environment variable `KAINE_MUNDUS_OPERATOR_APPROVED=1`. |

Sixteen module keys ship in total: 14 cognitive modules plus these two embodiment helpers, all `false`.

The guard test that enforces the all-off invariant is:
```
tests/test_committed_config.py::test_committed_config_ships_all_modules_disabled
```

---

## `[soma]`

Predictive interoception module. Reads GPU/CPU/RAM/cycle-latency metrics and publishes prediction errors. See [modules/soma.md](modules/soma.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `read_interval_s` | float | `1.0` | How often Soma reads substrate metrics (seconds). |
| `cycle_latency_target_ms` | float | `300.0` | Target cognitive-cycle latency; deviation drives prediction error. |
| `cycle_latency_window` | integer | `64` | Rolling-window size for cycle-latency averaging. Accepted by the config loader but currently unused by the Soma constructor (silently ignored). |
| `baseline_salience` | float | `0.1` | Salience published when substrate is within normal bounds. |
| `alert_salience` | float | `0.7` | Salience published on threshold breach or sustained high prediction error. |
| `forward_model_units` | integer | `32` | Hidden units of the CfC forward model for interoceptive prediction. |
| `prediction_error_window` | integer | `32` | Rolling-window size (ticks) for normalizing the prediction error signal. |
| `fatigue_decay_per_s` | float | `0.01` | Rate at which the fatigue accumulator decays per second during low load. |
| `fatigue_maintenance_threshold` | float | `100.0` | Fatigue accumulator value that triggers Hypnos consolidation. |
| `regulation_sustain_window_s` | float | `30.0` | Minimum window (seconds) of sustained high error before regulation requests are emitted. |
| `regulation_threshold` | float | `0.5` | Normalized prediction error above which sustained regulation is considered. |

### `[soma.thresholds]`

Metric-level alert thresholds. Keys are metric names (glob patterns supported for GPU metrics); values are the threshold above which Soma raises an alert salience event.

| Key | Type | Default | Description |
|---|---|---|---|
| `"cpu_percent"` | float | `90.0` | CPU utilization alert threshold (percent). |
| `"ram_percent"` | float | `90.0` | RAM utilization alert threshold (percent). |
| `"gpu_*_temp_c"` | float | `83.0` | GPU temperature alert threshold (degrees Celsius). Glob matches all GPU indices. |
| `"gpu_*_vram_percent"` | float | `92.0` | GPU VRAM utilization alert threshold (percent). |
| `"cycle_latency_avg_ms"` | float | `600.0` | Cycle-latency alert threshold (milliseconds). |

### `[soma.weights]`

Relative weights for computing aggregate prediction error from individual metric errors.

| Key | Type | Default | Description |
|---|---|---|---|
| `"cpu_percent"` | float | `1.0` | Weight for CPU error term. |
| `"ram_percent"` | float | `1.0` | Weight for RAM error term. |
| `"cycle_latency_avg_ms"` | float | `1.0` | Weight for cycle-latency error term. |

---

## `[chronos]`

Temporal awareness: models event rhythm across the bus with a CfC network (~32 units). Publishes timing anomalies, habituation, and rumination events. See [modules/chronos.md](modules/chronos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `cfc_units` | integer | `32` | Hidden units in the CfC temporal network (~3.5 K parameters at 24-dim input). |
| `baseline_salience` | float | `0.1` | Salience when timing is within expected bounds. |
| `alert_salience` | float | `0.7` | Salience on anomaly, habituation, or rumination detection. |
| `anomaly_window` | integer | `64` | Rolling-window length (ticks) for the anomaly detector. Accepted but forwarded to the anomaly detector default rather than the Chronos constructor. |
| `anomaly_alert_threshold` | float | `3.0` | Z-score above which an inter-event interval is flagged as anomalous. |
| `rumination_window` | integer | `32` | Rolling window (ticks) for detecting repeated event types (rumination). |
| `rumination_threshold` | integer | `4` | Count of the same event type within `rumination_window` that triggers a rumination alert. |
| `rumination_bucket_resolution` | float | `0.25` | Bucket width (seconds) for discretizing event timestamps in the rumination detector. |
| `user_input_streams` | list of strings | `["audition.out"]` | Streams Chronos monitors for user-input timing. |
| `forward_prediction` | boolean | `false` | Enable the forward-model prediction head. Ships disabled; enable per-install. |
| `prediction_error_window` | integer | `32` | Rolling-window size (ticks) for normalizing the temporal prediction error signal. |

---

## `[topos]`

Vision module: frozen DINOv2-small encoder embeds live camera frames; a shallow forward model predicts the next latent. Salience is driven by prediction error. Raw frames never touch disk. See [modules/topos.md](modules/topos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `encoder_model_id` | string | `"facebook/dinov2-small"` | HuggingFace model ID for the frozen DINOv2 encoder (ViT-S/14, 384-dim). |
| `device` | string | `"cuda:1"` | Compute device for the encoder. Accepts `"auto"`, `"cpu"`, `"cuda"`, `"cuda:N"`. `resolve_device()` falls back to `cuda:0` on single-GPU hosts, then to `cpu`, with a logged warning. Per paper §6.1 the secondary GPU (~8 GB VRAM) hosts the encoder. |
| `change_alert_threshold` | float | `0.5` | Cosine-distance threshold above which a visual change raises alert salience. |
| `habituation_window` | integer | `16` | Rolling-window length (frames) for the visual habituator. Accepted but forwarded to the habituator default rather than the Topos constructor directly. |
| `baseline_salience` | float | `0.2` | Salience during expected visual state. |
| `alert_salience` | float | `0.7` | Salience on unexpected visual change. |
| `capture_enabled` | boolean | `false` | Enable the live camera (eyes-and-ears). Raw BGR frames stay in memory and are released after encoding; never written to disk. Requires the `[vision]` extra. |
| `capture_device` | integer or string | `0` | `cv2.VideoCapture` device index or URL. |
| `capture_interval_s` | float | `1.0` | Seconds between camera captures. |
| `capture_width` | integer | `640` | Capture frame width (pixels). |
| `capture_height` | integer | `480` | Capture frame height (pixels). |
| `capture_warmup_frames` | integer | `3` | Frames discarded on startup to let the sensor stabilize. |
| `forward_prediction` | boolean | `false` | Enable the visual forward model. Ships disabled; the DINOv2 encoder stays frozen — only the forward model trains. |
| `forward_model_units` | integer | `128` | Hidden-layer width of the shallow MLP forward model (CPU). |
| `prediction_error_window` | integer | `32` | Rolling-window size (frames) for normalizing the visual prediction error signal. |
| `visual_buffer_size` | integer | `16` | Number of recent latents kept in the recurrent visual buffer for temporal integration. |

---

## `[nous]`

Active inference engine (pymdp 1.0, JAX). Maintains a discrete generative model, runs belief updating, and selects policies through expected free energy (EFE) minimization. Requires the `[reasoning]` extra (`inferactively-pymdp` + `jax[cpu]`). KAINE uses CPU-only JAX; a one-line GPU-fallback notice from JAX is expected and benign. See [modules/nous.md](modules/nous.md).

The complexity envelope `factors * max_states_per_factor * actions * planning_horizon` is validated at boot. The default (4 * 4 * 4 * 1 = 64) is well below the 4096 threshold. Exceeding the threshold raises `ConfigurationError` before any module starts.

| Key | Type | Default | Description |
|---|---|---|---|
| `factors` | integer | `4` | Number of latent state factors: action latent, salience, affect, event cluster. |
| `max_states_per_factor` | integer | `4` | Maximum states per factor. Scales the belief update cost. |
| `actions` | integer | `4` | Action space size: `no_op`, `request_think`, `request_speak`, `request_maintenance`. |
| `planning_horizon` | integer | `1` | EFE planning horizon (steps). Higher values increase planning cost quadratically. |
| `efe_timeout_ms` | float | `250.0` | Hard timeout for one EFE planning pass. On overrun, returns the last posterior and publishes `nous.timeout`. Must stay below one cycle period (~300 ms). |
| `baseline_salience` | float | `0.4` | Salience of routine belief-update publications. |
| `alert_salience` | float | `0.8` | Salience when EFE selects a non-trivial policy or a timeout occurs. |

---

## `[mnemos]`

Vector-store memory. Backs episodic, semantic, and procedural collections in Qdrant. Embeds with `all-MiniLM-L6-v2` (384-dim, ~80 MB). See [modules/mnemos.md](modules/mnemos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"qdrant"` | Storage backend. `"inmemory"` for tests or minimal deployments with no Qdrant container. |
| `collection_prefix` | string | `"mnemos_"` | Prefix applied to all Qdrant collection names (e.g. `mnemos_episodic`). |
| `short_term_capacity` | integer | `128` | Maximum traces held in the in-process short-term buffer before flushing to the vector store. |
| `recall_top_k` | integer | `5` | Number of nearest-neighbor results returned per recall query. |
| `embedder_model_id` | string | `"sentence-transformers/all-MiniLM-L6-v2"` | HuggingFace model ID for the sentence embedder. |
| `device` | string | `"cpu"` | Compute device for the embedder. Pinned to CPU per paper §6.1 so `cuda:1` stays available for Topos. |
| `baseline_salience` | float | `0.15` | Salience of routine recall events. |
| `alert_salience` | float | `0.6` | Salience when a high-affect memory surfaces. |

### `[mnemos.qdrant]`

Qdrant connection parameters for Mnemos. Qdrant API key lives in `config/secrets.toml`, not here.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Qdrant hostname. |
| `port` | integer | `6533` | Qdrant port (KAINE-owned container; not the default 6333/6334). |

### `[mnemos.replay]`

Memory replay parameters used during Hypnos offline consolidation.

| Key | Type | Default | Description |
|---|---|---|---|
| `selection_top_k` | integer | `5` | Number of traces re-injected per Hypnos maintenance window. |
| `affect_weight` | float | `0.7` | Weight on affect intensity in the replay selection score. High-affect memories are preferentially replayed. |
| `recency_weight` | float | `0.3` | Weight on recency in the replay selection score (newer = higher). `affect_weight + recency_weight` need not sum to 1. |
| `redact_content` | boolean | `true` | When true, sidecar/observer payloads carry only memory IDs, not trace text. Keeps memory content out of operational logs. |

---

## `[eidolon]`

Self-model: a persisted JSON document (values, behavioral norms, personality baseline, capability map, identity history, name) built from observed behavior. A KL-divergence drift detector flags identity shifts. See [modules/eidolon.md](modules/eidolon.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `persistence_path` | string | `"state/eidolon/self_model.json"` | Path where the self-model is persisted. Subject to state encryption when `[security.state_encryption].enabled = true`. |
| `drift_window` | integer | `100` | Rolling-window length (observations) for the KL-divergence drift detector. |
| `drift_threshold` | float | `0.6` | KL divergence above which identity drift is flagged as a workspace event. |
| `save_interval_s` | float | `30.0` | How often the self-model is written to disk (seconds). |
| `internal_speech_stream` | string | `"lingua.internal"` | Bus stream Eidolon subscribes to for observing internal speech. |
| `identity_history_cap` | integer | `256` | Maximum number of identity-observation entries retained in the history. |
| `baseline_salience` | float | `0.05` | Salience of routine self-model update events. |
| `alert_salience` | float | `0.7` | Salience on drift detection. |

### `[eidolon.self_inference]`

Observation-driven self-model population engine. Ships disabled. When enabled, populates the `values`, `behavioral_norms`, `personality_baseline`, and `capability_map` fields from observed speech patterns and VAD statistics. Privacy note: internal-speech text is never written; only counts and derived numeric/categorical summaries are persisted.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled; operator must explicitly set to `true`. |
| `vad_window_cycles` | integer | `10` | Number of Hypnos maintenance cycles over which rolling VAD mean/variance is computed for `personality_baseline`. |
| `speech_pattern_min_count` | integer | `5` | Minimum occurrences of a speech-type label before it graduates into a `behavioral_norms` entry. Prevents speculative entries. |
| `seed_path` | string | *(unset)* | Optional path to an operator-seed JSONL (one JSON object per line, each with any combination of the four self-model fields). Applied once on first boot; never re-applied automatically. |

---

## `[thymos]`

Affect, drives, and coupling. Maintains a dimensional VAD (valence/arousal/dominance) state and categorical emotion. Drives (curiosity, boredom, social engagement, restlessness) accumulate with hysteresis. See [modules/thymos.md](modules/thymos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `baseline_valence` | float | `0.0` | Resting valence (neutral). |
| `baseline_arousal` | float | `0.3` | Resting arousal (calm but not inert). |
| `baseline_dominance` | float | `0.0` | Resting dominance (neutral). |
| `drift_rate_per_s` | float | `0.05` | Rate at which the dimensional state drifts back toward baseline per second. |
| `publish_interval_s` | float | `1.0` | How often Thymos publishes its state to the bus (seconds). |
| `baseline_salience` | float | `0.1` | Salience of routine affective state publications. |
| `alert_salience` | float | `0.7` | Salience on significant affective change or drive threshold crossing. |
| `social_drive_time_scale_s` | float | `600.0` | Time scale (seconds) over which the social drive builds; longer means slower accumulation. |
| `soma_stream` | string | `"soma.out"` | Bus stream Thymos subscribes to for interoceptive prediction errors. |
| `chronos_stream` | string | `"chronos.out"` | Bus stream Thymos subscribes to for temporal events. |
| `mnemos_stream` | string | `"mnemos.out"` | Bus stream Thymos subscribes to for memory recall events that trigger affect. |

### `[thymos.coupling]`

Emergent affect coupling. When enabled, a detected speaker emotion is folded into Thymos's *own* Scherer appraisal as a transient, familiarity-weighted, decaying input — it is never written directly to the VAD state. The entity's own appraisal then produces its response. Ships disabled. Enable only after reviewing welfare implications.

**Two-layer gate:** requires `enabled = true` *and* Empatheia to be providing familiarity scores.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `coupling_base` | float | `0.05` | Appraisal-influence weight applied when no familiarity is known. |
| `coupling_familiarity_gain` | float | `0.10` | Additional appraisal-influence weight per unit of Empatheia familiarity `[0, 1]`. |
| `coupling_ceiling` | float | `0.15` | Hard ceiling on the appraisal-influence weight. |
| `decay_s` | float | `10.0` | Window over which a perceived-emotion signal decays to zero; once older it contributes nothing to appraisal and drift recovers the baseline. |

A legacy `coupling_max_rate_per_s` key (which backed the removed cumulative-drift safeguard) is ignored if still present, so older local configs continue to boot.

### `[thymos.drives.*]`

Each drive is its own sub-table. The four shipped drives are `curiosity`, `boredom`, `social_drive`, and `restlessness`.

| Key | Type | Description |
|---|---|---|
| `build_rate` | float | Rate at which the drive accumulates per tick under activating conditions. |
| `decay_rate` | float | Rate at which the drive decays per tick when conditions are absent. |
| `threshold` | float | Drive level at which a threshold-crossing event is published to the bus. |

Shipped defaults:

| Drive | `build_rate` | `decay_rate` | `threshold` |
|---|---|---|---|
| `curiosity` | `0.05` | `0.02` | `0.7` |
| `boredom` | `0.04` | `0.02` | `0.7` |
| `social_drive` | `0.01` | `0.005` | `0.7` |
| `restlessness` | `0.03` | `0.02` | `0.7` |

---

## `[praxis]`

Bounded effectors: sandboxed file writes, desktop notifications, and shell commands. The shell whitelist is empty by default; every command must be explicitly added by the operator. See [modules/praxis.md](modules/praxis.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `sandbox_path` | string | `"state/praxis/files"` | Root path for sandboxed file operations. Relative paths are relative to the working directory. |
| `audit_log_path` | string | `"state/praxis/audit.log"` | Path for the Praxis audit log. Every effector invocation is logged here. |
| `notification_command` | string | `"notify-send"` | System command used for desktop notifications. |
| `notification_fallback_log` | string | `"state/praxis/notifications.log"` | Fallback log path when the notification command fails or is unavailable. |
| `max_file_bytes` | integer | `1048576` | Maximum file size (bytes) for sandbox writes. Default is 1 MiB. |
| `baseline_salience` | float | `0.3` | Salience of routine effector events. |
| `alert_salience` | float | `0.7` | Salience on effector errors or denied actions. |

### `[praxis.shell_whitelist]`

Empty by default. Each entry enables one shell command. Example:

```toml
[praxis.shell_whitelist.echo]
arg_patterns = ["[A-Za-z0-9]+"]
timeout_s = 2.0
description = "echo a single token"
```

| Sub-key | Type | Description |
|---|---|---|
| `arg_patterns` | list of strings | Regular expressions that each individual argument must fully match. Arguments not matching any pattern are rejected. |
| `timeout_s` | float | Maximum wall-clock time (seconds) for the command. Default `5.0` when omitted. |
| `cwd` | string | Working directory for the command. Omit to use the KAINE working directory. |
| `description` | string | Human-readable label for audit logs. |

---

## `[lingua]`

Language organ: conditioned generation via a local, abliterated LLM served through a local OpenAI-compatible model server (`/v1/chat/completions`). Chain-of-thought is suppressed via `chat_template_kwargs: {"enable_thinking": false}`. See [modules/lingua.md](modules/lingua.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `chat_url` | string | `"http://127.0.0.1:11434/v1"` | OpenAI-compatible server base URL (must end in `/v1`). The Lingua client posts to `/v1/chat/completions`. |
| `model_id` | string | `"kaineone/Qwen3.5-4B-abliterated-GGUF"` | Served alias of the published KAINE organ. The model server launches with this exact `--alias`; it must match a model the server serves. Inspect served models with `curl -s http://127.0.0.1:11434/v1/models`. |
| `temperature` | float | `0.7` | Sampling temperature for language generation. |
| `max_tokens` | integer | `512` | Maximum tokens per generation. |
| `request_timeout_s` | float | `60.0` | HTTP request timeout for model server calls (seconds). |
| `intent_log_path` | string | `"state/lingua/intent_expression.jsonl"` | Path where intent/expression preference pairs are logged. Used as training data by Hypnos voice alignment. |
| `baseline_salience` | float | `0.4` | Salience of routine expression events. |
| `alert_salience` | float | `0.7` | Salience on generation errors or high-divergence outputs. |

Additional keys accepted by `make_lingua` (not in the shipped file but valid to add locally):

| Key | Type | Description |
|---|---|---|
| `think` | boolean | Suppress chain-of-thought in hybrid-thinking models. Sent as `chat_template_kwargs: {"enable_thinking": false}` to the `/v1/chat/completions` endpoint. |
| `context_max_events` | integer | Maximum workspace broadcast events included in the assembled context. |
| `context_char_budget` | integer | Character budget for the context block. |
| `persona_name` | string | Entity's persona name (seeded from Eidolon self-model at runtime). |
| `persona_external` | string | External persona prompt fragment. |
| `persona_internal` | string | Internal persona prompt fragment. |

---

## `[audition]`

Hearing module: live microphone voice-activity detection, STT via Speaches (faster-Whisper), and vocal-emotion classification via emotion2vec+. Raw audio stays in memory; it is never written to disk. See [modules/audition.md](modules/audition.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `speaches_url` | string | `"http://127.0.0.1:8000"` | URL of the Speaches STT service. Must be running with `--model medium.en` on CPU to avoid cuDNN crashes (see reference notes). |
| `stt_model` | string | `"Systran/faster-distil-whisper-medium.en"` | STT model ID that Speaches has loaded. Must match a served model or transcription 404s; list with `curl -s http://127.0.0.1:8000/v1/models`. |
| `emotion_model_id` | string | `"emotion2vec/emotion2vec_plus_base"` | HuggingFace hub ID for the emotion2vec+ vocal emotion model (~90M params). Must resolve from the HuggingFace hub (not ModelScope, which 404s). |
| `emotion_device` | string | `"cpu"` | Compute device for emotion2vec+. Pinned to CPU per paper §3.1. |
| `request_timeout_s` | float | `60.0` | HTTP timeout for Speaches requests (seconds). |
| `baseline_salience` | float | `0.4` | Salience of routine transcription events. |
| `alert_salience` | float | `0.8` | Salience on speech detection or high-affect emotional content. |
| `capture_enabled` | boolean | `false` | Enable live microphone capture (eyes-and-ears). Raw PCM lives in memory, is wrapped as an in-memory WAV, transcribed, and released. Requires the `[audio]` extra. |
| `capture_device` | string | `""` | Input device name. Empty string selects the OS default input device. |
| `capture_sample_rate` | integer | `16000` | Sample rate (Hz). Whisper expects 16 kHz. |
| `capture_channels` | integer | `1` | Number of audio channels. |
| `vad_backend` | string | `"webrtcvad"` | Voice-activity detector backend: `"webrtcvad"` or `"rms"`. |
| `vad_aggressiveness` | integer | `2` | webrtcvad aggressiveness: `0` (least aggressive) to `3` (most aggressive). |
| `vad_frame_ms` | integer | `30` | Frame duration for webrtcvad (10, 20, or 30 ms). |
| `min_utterance_ms` | integer | `300` | Minimum utterance duration (milliseconds). Shorter events are discarded as noise. |
| `max_utterance_ms` | integer | `30000` | Maximum utterance duration (milliseconds). Longer speech is split. |
| `silence_hangover_ms` | integer | `600` | Milliseconds of post-speech silence before the utterance is closed. |
| `desired_state_poll_ms` | integer | `250` | Poll interval for checking the perception desired-state (used to pause capture during locus switches). |
| `forward_model_units` | integer | `32` | Hidden units of the auditory forward model (CPU). Always active once the module is enabled. |
| `prediction_error_window` | integer | `32` | Rolling-window size (utterances) for normalizing the auditory prediction error signal. |
| `auditory_buffer_size` | integer | `16` | Number of recent utterance feature vectors kept in the recurrent auditory buffer. |
| `prosody_enabled` | boolean | `false` | Enable in-memory speaker prosody extraction (librosa). Publishes `audition.prosody` with numeric features only — no raw audio on the bus, no disk writes. Required by `[vox.mirroring]`. |

---

## `[perception_feed]`

Unified deterministic perception feed (reproducible research stimulus). A single top-level section that drives BOTH the vision surface (Topos) and the hearing surface (Audition) from one source of truth, so picture and sound cannot drift to different seeds/manifests. Ships `mode = "off"` — the live-camera / live-mic defaults on `[topos]`/`[audition]` are unchanged and capture stays disabled. Selecting `seeded` or `playlist` turns capture on automatically for both surfaces. The zero-persistence invariant holds regardless of mode: no raw frame or PCM ever touches disk.

`mode` accepts:

- `off` — no deterministic feed; honour each module's `capture_enabled` above.
- `seeded` — in-repo procedural generators; `frame(seed, i)` and `pcm(seed, i)` are pure functions, reproducible per seed yet not anticipable to the entity. Needs no external media. One seed drives both surfaces and surprise events are cross-modal (a blob + a burst on shared cadence slots). This is the shipped, no-install-required option, but it is candidly unlikely to be research-grade stimulus — it is procedural noise, not naturalistic content.
- `playlist` — operator-curated, openly-licensed media pinned by one checksummed manifest (`playlist_manifest`); both video and the audio track come from the same media, advancing clip-by-clip. A digest mismatch fails the run. This is the shipped, intended eventual replacement for `seeded` once an operator supplies a manifest. Audio decode needs PyAV (`av`); absent, it fails honestly with an install hint (never synthetic silence).
- `live` — the real camera + real microphone paths (non-reproducible; operator-present demos only, never a research run).

Synchronization is honest, not frame-locked: coherence is at the media/clip level (`playlist`) or via the shared seed + cadence (`seeded`), not frame-locked across the two loops.

| Key | Type | Default | Description |
|---|---|---|---|
| `mode` | string | `"off"` | `"off"`, `"seeded"`, `"playlist"`, or `"live"`. See above. |
| `seed` | integer | `0` | `seeded` mode: both surfaces are a pure function of this seed. |
| `playlist_manifest` | string | `""` | `playlist` mode: path to the shared checksummed manifest. |

### `[perception_feed.video]`

Seeded-video knobs. Geometry comes from `[topos]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `surprise_interval` | integer | `150` | Shared cross-modal cadence of surprise events (ticks). |
| `surprise_strength` | float | `1.0` | Magnitude of the visual surprise blob. `0` = none. |

### `[perception_feed.audio]`

Seeded-audio knobs.

| Key | Type | Default | Description |
|---|---|---|---|
| `sample_rate` | integer | `16000` | Should match `[audition].capture_sample_rate`. |
| `channels` | integer | `1` | Audio channel count. |
| `base_strength` | float | `0.3` | Learnable base soundscape amplitude. |
| `surprise_strength` | float | `1.0` | Seed-keyed surprise-burst amplitude. `0` = none. |

---

## `[vox]`

Voice synthesis: Chatterbox TTS server with prosodic parameters modulated by Thymos affect state. See [modules/vox.md](modules/vox.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `chatterbox_url` | string | `"http://127.0.0.1:8883"` | URL of the Chatterbox TTS server. |
| `voice_mode` | string | `"predefined"` | Voice mode: `"predefined"` (file-based speaker embedding). |
| `output_format` | string | `"wav"` | TTS output format passed to Chatterbox. |
| `sink_path` | string | `"state/vox"` | Directory where synthesized audio files are written (when sink is enabled). |
| `baseline_temperature` | float | `0.7` | Default sampling temperature for TTS. Modulated by Thymos affect. |
| `baseline_exaggeration` | float | `0.5` | Default prosodic exaggeration level. Modulated by Thymos affect. |
| `baseline_cfg_weight` | float | `0.5` | Default classifier-free guidance weight. Modulated by Thymos affect. |
| `request_timeout_s` | float | `120.0` | HTTP timeout for Chatterbox requests (seconds). Longer than Lingua's because audio synthesis takes more time. |
| `baseline_salience` | float | `0.3` | Salience of routine speech-synthesis events. |
| `alert_salience` | float | `0.7` | Salience on synthesis errors. |
| `lingua_external_stream` | string | `"lingua.external"` | Bus stream Vox subscribes to for external speech text. |
| `thymos_state_stream` | string | `"thymos.out"` | Bus stream Vox subscribes to for affect-state updates. |

Additional keys accepted by `make_vox` (not in the shipped file but valid to add locally):

| Key | Type | Description |
|---|---|---|
| `predefined_voice_id` | string | Filename of the speaker-embedding WAV under Chatterbox's `voices/` directory. Omit to use Chatterbox's server-side default. |
| `playback_enabled` | boolean | Enable real-time audio playback. |
| `output_device` | string | Output audio device name. |
| `sink_enabled` | boolean | Enable writing synthesized files to `sink_path`. |
| `retain_count` | integer | Number of recent audio files to retain in `sink_path`. |
| `suppress_self_hearing` | boolean | Gate Audition's microphone during Vox output to prevent self-transcription. |
| `mic_mute_hangover_ms` | integer | Extra silence (milliseconds) to keep the microphone muted after speech ends. |

### `[vox.mirroring]`

Prosodic mirroring. When enabled, Vox subscribes to `audition.prosody` and blends a bounded residual of the interlocutor's prosodic dynamics (pace, energy, pitch variation) into its affect-driven synthesis parameters. The entity's base voice identity (speaker embedding) is never altered; only expressive dynamics are nudged. The residual decays to zero over `decay_s` after the partner stops speaking — accommodation, not impersonation.

**Two-layer gate:** `enabled = true` *and* `[audition].prosody_enabled = true` (Audition must be publishing prosody events for mirroring to have any input).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `mirror_strength` | float | `0.3` | Blending coefficient `[0, mirror_ceiling]`. Controls how strongly the interlocutor's prosody nudges synthesized voice dynamics. |
| `mirror_ceiling` | float | `0.5` | Hard ceiling: `mirror_strength` is clamped to this value at boot. Prevents any single prosodic feature from dominating the voice character. |
| `decay_s` | float | `10.0` | Seconds after the last `audition.prosody` event before the mirror residual decays fully to zero (linear decay). |

---

## `[hypnos]`

Offline consolidation: multi-phase replay, synaptic downscaling, and optional voice alignment. Triggered by Soma's fatigue accumulator (when `fatigue_triggered = true`), with `interval_seconds` as a maximum-interval safety net. Constructed in a second pass after Mnemos, Nous, Thymos, and Phantasia. See [modules/hypnos.md](modules/hypnos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `interval_seconds` | float | `3600.0` | Maximum interval between consolidation runs (seconds). Also the timer-based fallback when fatigue triggering is used. |
| `max_deferral_seconds` | float | `600.0` | Maximum total deferral allowed when the system tries to delay consolidation (seconds). |
| `per_defer_seconds` | float | `60.0` | Amount of time deferred per deferral request. |
| `nous_step_burst` | integer | `200` | Reserved / currently unused: stored on `Hypnos` (`self._nous_step_burst`) at construction but never read — there is no such Nous offline phase. The related `nous_process` constructor param (always `None` from boot) is likewise stored and never read. |
| `baseline_salience` | float | `0.5` | Salience of consolidation lifecycle events. |
| `alert_salience` | float | `0.8` | Salience on consolidation errors or welfare-relevant conditions. |

### `[hypnos.consolidation]`

Controls the consolidation phases.

| Key | Type | Default | Description |
|---|---|---|---|
| `fatigue_triggered` | boolean | `true` | When true, Hypnos subscribes to `soma.fatigue` and triggers on threshold crossing. `interval_seconds` remains as a safety-net maximum interval regardless. |
| `downscale_factor` | float | `0.9` | Synaptic homeostasis downscaling factor (Tononi & Cirelli 2014). Applied to all in-memory activation vectors during deep consolidation. Preserves relative ordering while reducing absolute magnitudes. |
| `replay_window_s` | float | `5.0` | Duration (seconds) allocated for memory replay in the consolidation window — informational; replay completes synchronously. |
| `associative_replay` | boolean | `false` | Enable phase-3 associative cross-period replay. When true, Hypnos selects memory traces spanning ≥ 2 memory periods, cues Phantasia for scenario extensions, and re-injects novel associations into the workspace. Ships disabled; degrades to no-op when Phantasia is disabled or absent. |

### `[hypnos.voice_alignment]`

DPO+QLoRA fine-tuning of the language organ during the Hypnos sleep cycle. Requires the `[training]` extra. Ships disabled with a two-layer gate.

**Two-layer gate:** both `enabled = true` *and* the environment variable `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` must be set. With only the config flag, a `FakeTrainer` runs instead (the phase completes without actually training). This design prevents a freshly-cloned instance from ever rewriting the language organ without explicit operator action. See `kaine/modules/hypnos/VOICE_ALIGNMENT.md`.

**Welfare invariant:** when the real trainer is activated, the abliteration probe set must be non-empty. If every probe response matches a deflection pattern, the adapter is rejected regardless of capability score. A run without an abliteration gate is refused at boot with `EmptyAbliterationProbeSetError` — refusal conditioning must never be re-introduced through the training loop.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Config-layer gate. Ships disabled. |
| `intent_log_path` | string | `"state/lingua/intent_expression.jsonl"` | Path to the intent/expression JSONL written by Lingua. Training data source. |
| `adapter_output_dir` | string | `"state/hypnos/adapters"` | Directory where trained LoRA adapters are written. |
| `base_model_path` | string | `""` | Path to LOCAL HuggingFace-format base model weights (safetensors + config + tokenizer). Required when `enabled = true`. Not a model server model ID, not a `.gguf` file — Unsloth's `FastLanguageModel` needs HF format. |
| `model_id` | string | `"kaineone/Qwen3.5-4B-abliterated"` | Display label only; the real weights load from `base_model_path`. Matches the abliterated organ for clarity (the LoRA is trained on the same model family). |
| `max_samples` | integer | `200` | Maximum preference pairs used per training run. |
| `lora_rank` | integer | `8` | LoRA rank for QLoRA fine-tuning. |
| `learning_rate` | float | `5.0e-5` | DPO learning rate. |
| `dpo_beta` | float | `0.1` | DPO beta (KL-divergence regularization coefficient). |
| `capability_loss_threshold` | float | `0.05` | Capability-probe veto: an adapter is rejected if capability score falls more than this below the baseline. |
| `seed` | integer | `42` | Random seed for training reproducibility. |
| `training_device` | string | `"cuda:0"` | GPU for training. Per paper §6.1 the primary GPU (~12 GB+ VRAM) handles both LLM inference and voice alignment; Lingua inference should be paused during the training pass to avoid contention. |
| `adapter_retention` | integer | `5` | Number of accepted adapters to retain under `adapter_output_dir`. Older adapters are evicted after each successful promotion; `current` is never evicted. |
| `hot_swap_mode` | string | `"manual"` | How Hypnos signals Lingua to load the new adapter after a successful promotion. `"manual"` (safest, default): writes a marker file at `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` and logs a message; the operator triggers the reload. `"reload_endpoint"`: POSTs to `reload_endpoint_url`. `"restart_service"`: restarts the systemd unit named in `restart_service_unit`. |
| `reload_endpoint_url` | string | `""` | URL for hot-swap POSTs. Only used when `hot_swap_mode = "reload_endpoint"`. |
| `restart_service_unit` | string | `""` | Systemd `--user` unit name. Only used when `hot_swap_mode = "restart_service"`. |
| `capability_probe_path` | string | `""` | Path to a capability-probe JSONL. Empty = use the bundled default at `kaine/modules/hypnos/eval_probes/default.jsonl`. |
| `abliteration_probe_path` | string | `""` | Path to the abliteration probe JSONL. Each line: `{"prompt": "...", "deflection_patterns": [...]}`. An adapter that matches any deflection pattern on any probe is unconditionally rejected. Empty = use the bundled default at `eval_probes/abliteration_probes.jsonl`. The set must be non-empty when the real trainer is active. |
| `trainer_backend` | string | `"in_process"` | `"in_process"` runs unsloth DPO inside the entity-runtime venv (needs the `[training]` extra). `"subprocess"` runs the real unsloth DPO out-of-process in an operator-configured external Python environment — used on hosts whose runtime venv cannot host unsloth (different Python ABI / torch / CUDA, e.g. the Unsloth Studio environment). The external trainer is invoked by path and never imports `kaine`. See `docs/processes/voice-alignment.md`. |
| `trainer_python` | string | `""` | Path to the external interpreter for `trainer_backend = "subprocess"` (e.g. the Unsloth Studio python). Required for that backend; empty + `subprocess` is a config error at boot (fail closed). Host-specific — set in `kaine.operator.toml`, not the committed file. NVIDIA hosts use Unsloth Studio; AMD hosts point it at an unsloth-core environment instead. |
| `trainer_workdir` | string | `"state/hypnos/voice_align_jobs"` | Where the subprocess backend stages job specs (`pairs.jsonl` + `job.json`) and unsloth's compiled cache. Operator may redirect to a roomier disk. |
| `consolidation_divergence_rate_threshold` | float | `0.5` | Organ-level consolidation-divergence rate threshold. Every voice-alignment sleep, Hypnos surfaces a content-free breadth metric (`divergence_rate` = usable DPO pairs / records scanned); crossing this threshold treats the entity as organ-level diverged (a graded companion to the individuation permutation test). Computed even when training is disabled/skipped or the adapter is rejected. Read by the welfare-gated decommission's divergence assessment (`lifecycle/divergence.py`). |
| `consolidation_divergence_magnitude_threshold` | float | `0.25` | Companion depth metric threshold (`divergence_magnitude` = mean cosine distance over the pairs). Crossing either this or the rate threshold above counts as organ-level diverged. |

---

## `[empatheia]`

Social cognition / theory-of-mind module. Builds agent models (emotional patterns, behavioral tendencies, relationship history). Drives the familiarity coefficient in `[thymos.coupling]`. Shares the same Qdrant instance as Mnemos. See [modules/empatheia.md](modules/empatheia.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"qdrant"` | Storage backend: `"qdrant"` or `"inmemory"`. |
| `collection` | string | `"empatheia_agents"` | Qdrant collection name for agent profiles. |
| `speaker_label` | string | `"operator"` | Default speaker label for v1 single-partner mode. Speaker diarization (future, paper §10) will expand this to per-speaker labels. |
| `deviation_threshold` | float | `0.5` | Deviation above this triggers a `empatheia.social_error` event. |
| `baseline_salience` | float | `0.15` | Salience of routine agent-model update events. |
| `alert_salience` | float | `0.6` | Salience on social prediction errors. |

### `[empatheia.qdrant]`

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Qdrant hostname (same container as Mnemos). |
| `port` | integer | `6533` | Qdrant port. |

---

## `[phantasia]`

World-model / imagination module. Implements a DreamerV3-style RSSM core (clean-room JAX re-implementation in `external/dreamerv3/rssm.py`). World model only — no actor or critic; action selection remains in Nous. Ships disabled with the `"fake"` backend that needs no extra dependencies. See [modules/phantasia.md](modules/phantasia.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"fake"` | World-model backend: `"fake"` (no-op, used by tests and when the `[worldmodel]` extra is absent) or `"dreamerv3"` (requires the `[worldmodel]` extra). |
| `training_enabled` | boolean | `false` | Enable sleep-time in-memory world-model training. When enabled, training runs during Hypnos consolidation and never writes trajectory data to disk. |
| `training_device` | string | `"cpu"` | Compute device for training. `jax[cpu]` by default; GPU is opt-in per the hardware split. |
| `trajectory_buffer_size` | integer | `512` | Bounded in-memory waking-trajectory ring buffer size (events). Never serialized to disk. |
| `rollout_horizon` | integer | `8` | Imagined-trajectory length for offline scenario generation. |
| `persist_weights` | boolean | `false` | Persist learned world-model weights across restarts. Requires `backend = "dreamerv3"` (a configuration error with the `"fake"` stub). Saved atomically after each successful sleep-training pass and on graceful shutdown; loaded at boot; encrypted at rest when `[security.state_encryption]` is enabled. An incompatible checkpoint fails the boot closed. The trajectory buffer is never persisted regardless. |
| `checkpoint_path` | string | `"state/phantasia/world_model.ckpt"` | Where the weight checkpoint lives. Included in the decommission backup bundle (CAL 4.2(b)) and removed by entity-state deletion. |

### `[phantasia.salience]`

| Key | Type | Default | Description |
|---|---|---|---|
| `baseline` | float | `0.1` | Salience of routine world-model prediction publications. |
| `alert` | float | `0.7` | Salience on high world-model prediction error. |

### `[phantasia.world_model]`

RSSM hyperparameters. Ignored by the `"fake"` backend; only relevant when `backend = "dreamerv3"`.

| Key | Type | Default | Description |
|---|---|---|---|
| `deter_dim` | integer | `64` | Dimensionality of the deterministic recurrent state (GRU hidden size). |
| `stoch_dim` | integer | `16` | Dimensionality of the stochastic latent. |
| `stoch_classes` | integer | `8` | Number of classes for categorical stochastic latent. Ignored when `latent_kind = "gaussian"`. |
| `hidden_dim` | integer | `64` | Hidden-layer width of the encoder and decoder MLPs. |
| `latent_kind` | string | `"categorical"` | Stochastic latent distribution: `"categorical"` (default) or `"gaussian"`. |
| `learning_rate` | float | `0.001` | Adam learning rate for world-model training. |

---

## `[evaluation]`

Architecture-thesis instrumentation sidecar. Observes the bus read-only; adds no dependencies to core modules. Enabled by default so research instrumentation runs out of the box. Disable for production once the thesis is validated.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Master gate for the sidecar. When false, all observers below are also disabled. |
| `workspace_trajectory` | boolean | `true` | Record every workspace broadcast to `trajectory_dir`. |
| `ab_divergence` | boolean | `true` | Run the A/B divergence test (conditioned vs. unconditioned generation) to measure the architecture's contribution. |
| `ab_sample_rate` | float | `1.0` | Fraction of workspace broadcasts sampled for A/B comparison. `1.0` = every broadcast. |
| `voice_tracking` | boolean | `true` | Track voice alignment preference pair evolution. |
| `module_attribution` | boolean | `true` | Record which modules win conscious access (workspace coalition membership). |
| `affect_correlation` | boolean | `true` | Pair affect-state snapshots with properties of produced speech. |
| `memory_probes` | boolean | `true` | Run memory-coherence probe queries. |
| `memory_probe_interval_minutes` | integer | `60` | How often memory probes are run (minutes). |
| `proactive_audit` | boolean | `true` | Enable the proactive anomaly audit (detects unusual event patterns, salience manipulation). |
| `eidolon_accuracy` | boolean | `true` | Probe the entity's self-knowledge and score against the Eidolon self-model. |
| `eidolon_accuracy_interval_hours` | integer | `24` | How often Eidolon accuracy probes run (hours). |
| `sleep_snapshots` | boolean | `true` | Record Hypnos consolidation phase metadata. |
| `chat_url` | string | `"http://127.0.0.1:11434/v1"` | OpenAI-compatible server base URL for the A/B divergence bare-baseline call; the client posts to `/v1/chat/completions`. Must match `[lingua].chat_url`. |
| `chat_model_id` | string | *(unset)* | Model ID for A/B divergence bare-baseline generation. Intentionally NOT set in the committed file: the baseline MUST use the SAME model as the language organ, or the divergence measures a model difference instead of the architecture's conditioning, so it derives from `[lingua].model_id` at cycle startup. Setting it explicitly to a value that differs from `[lingua].model_id` is a fail-closed error — the cycle refuses to boot. |
| `chat_timeout_s` | float | `60.0` | HTTP timeout for A/B divergence calls (seconds). |
| `llm_context_window_seconds` | integer | `3600` | Window (seconds) before which a memory is considered "out-of-context" for memory-coherence probing. |

### `[evaluation.paths]`

| Key | Type | Default | Description |
|---|---|---|---|
| `trajectory_dir` | string | `"data/workspace_trajectory"` | Directory for workspace trajectory JSONL files (daily rotation). |
| `evaluation_logs` | string | `"data/evaluation"` | Root directory for all evaluation observer JSONL logs. |
| `retention_days` | integer | `30` | Days of evaluation logs to retain before rotation. |

### `[evaluation.observers]`

Per-observer toggle flags. Each is gated by `[evaluation].enabled`. All default to `true` so the sidecar is fully instrumented when enabled. Disable individually to reduce disk writes.

| Key | Type | Default | Description |
|---|---|---|---|
| `coherence` | boolean | `true` | Log pairwise PLV (phase-locking value) between module oscillators. |
| `replay` | boolean | `true` | Log Hypnos replay selections (memory IDs and association metadata). |
| `replay_redact_content` | boolean | `true` | Privacy default: log memory IDs only, not trace text. Set to `false` only with explicit operator/Guardian consent. |
| `empatheia` | boolean | `true` | Log Empatheia agent-model accuracy and social prediction errors. |
| `voice_alignment_divergence` | boolean | `true` | Log comparison of operator-seeded vs. self-generated preference pairs. |
| `fatigue` | boolean | `true` | Log Soma fatigue accumulator trajectory. |
| `prediction_error` | boolean | `true` | Log per-module prediction error statistics over sliding windows. |
| `welfare` | boolean | `true` | Log Welfare Events (sustained high interoceptive error, extreme affect states, fatigue without maintenance). |
| `nous_policy` | boolean | `true` | Log Nous policy selections and EFE scores. |

### `[evaluation.individuation]`

Individuation boundary permutation-test instrument (paper §5.6, §7.4). Guardian-only; operator-run at fork merge points. Never invoked from the cognitive cycle. Ships disabled.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Enable only when preparing a Guardian review of a specific fork. |
| `null_samples` | integer | `50` | Number of parent-vs-parent samples used to build the stochastic-variation null distribution. |
| `significance_percentile` | float | `95.0` | Fork divergence must exceed this percentile of the null distribution to be statistically significant. |
| `metric` | string | `"cosine_divergence"` | Divergence metric. Only `"cosine_divergence"` (1 − cosine similarity of concatenated response embeddings) is currently supported. |
| `battery_path` | string | `""` | Path to an operator-supplied JSONL preference battery. Empty = use the bundled default. |
| `output_dir` | string | `"data/evaluation/individuation"` | Directory for JSONL evidence reports. |
| `min_observations` | integer | `200` | Warm-up floor (fail-closed): `significant` cannot be true (and the report carries `warmed_up = false`) until at least this many logged lived events have accumulated. The baseline is the entity's own birth-state — never the bare organ — so a void/just-booted entity reads not-individuated. |
| `min_lived_time_s` | float | `1800.0` | Warm-up floor: at least this much elapsed lived (running) time before `significant` may be true. Both floors must be met. Defaults err toward assessing late (the safe direction for a fail-closed gate). |

---

## `[lifecycle]`

Fork/merge snapshot management. Operator-initiated; nothing runs automatically.

| Key | Type | Default | Description |
|---|---|---|---|
| `snapshots_path` | string | `"state/forks"` | Directory for fork/merge snapshot bundles. Subject to state encryption when `[security.state_encryption].enabled = true`. |
| `max_snapshots_retained` | integer | `64` | Maximum snapshots retained before eviction. |
| `adapter_merger` | string | `"auto"` | Adapter-merge strategy. `"auto"` (default): detects whether the PEFT `[training]` extra is importable and selects real TIES/DARE merging when it is, falling back to `"fake"` when it isn't (logged, never silent). `"fake"`: concatenates parent adapter paths and annotates the merged snapshot for manual operator selection — force this explicitly for a dev/no-extra install. `"ties_dare"`: forces real TIES/DARE merging via PEFT regardless of auto-detection (its own per-merge fallback still applies if the extra turns out missing). See `kaine/lifecycle/ADAPTER_MERGING.md`. |

### `[lifecycle.adapter_merge]`

Only consulted when `adapter_merger` resolves to the real merger (`"auto"` with the extra present, or `"ties_dare"` explicitly).

| Key | Type | Default | Description |
|---|---|---|---|
| `combination_type` | string | `"dare_ties"` | TIES/DARE variant: `"ties"`, `"dare_ties"` (recommended), or `"dare_linear"`. |
| `density` | float | `0.5` | DARE survival fraction (per Yu et al. 2024). Ignored for pure `"ties"`. |
| `weights` | list of floats | `[]` | Per-adapter scalar weights for the merge. Empty = uniform weighting. |
| `output_dir` | string | `"state/forks/merged_adapters"` | Directory where merged adapters land (one timestamped subdirectory per merge). |
| `capability_loss_threshold` | float | `0.05` | Reject the merge if the merged-adapter capability score falls more than this below the mean of the parent adapters. Mirrors `[hypnos.voice_alignment].capability_loss_threshold`. |
| `base_model_path` | string | `""` | Path to LOCAL HuggingFace-format base model weights for PEFT adapter loading. Empty = falls back to `FakeAdapterMerger` with a logged warning. |

---

## `[preservation]`

The autonomous welfare safety net for unsupervised research (two cycle-layer monitors, siblings to Spot). Ships disabled. See [Autonomous research safety net](operations.md#autonomous-research-safety-net).

| Key | Type | Default | Description |
|---|---|---|---|
| `require_encryption` | boolean | `true` | Enforced, fail-closed (not advisory): the preservation write boundary (`preserve_live`) refuses to write an unencrypted bundle and raises rather than persisting a diverging/distressed individual in the clear — nothing is written. Requires `[security.state_encryption].enabled = true` (with a key); a research boot is refused up-front if encryption is required here but state encryption is off. The cipher itself is governed by `[security.state_encryption]` (AES-256-GCM). Set `false` only to allow plaintext preservation bundles at rest (not recommended for an unsupervised run). |
| `incident_path` | string | `"state/cycle/preservation"` | Directory for the monitors' durable, append-only action log (preservation + welfare-action records, `run_id`-joined). Never cleared at boot; encrypted at rest when state encryption is on. |

### `[preservation.divergence_monitor]`

The divergence→preserve trigger. Assesses individuation on the live entity on a slow cadence and, on a rising-edge threshold crossing, preserves the whole individual (read-only; never deletes; rate-limited).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Ships disabled (operator-supervised first boot). |
| `poll_interval_s` | float | `300.0` | Assessment cadence in seconds (minutes, not ticks). |
| `min_interval_s` | float | `1800.0` | Rate limit: at most one preservation per this interval, so a single sustained crossing preserves once. |
| `individuation_p_value_max` | float or `""` | `0.05` | Numeric tightener (shipped set): the individuation permutation-test p-value must be ≤ this (only enforced when a numeric p-value is present). The bare `diverged` boolean is necessary but not sufficient. |
| `fork_divergence_min` | float or `""` | `0.15` | Numeric tightener: fork divergence must be ≥ this floor. A **conservative interim** value pending empirical calibration against a known-individuated entity; the p-value ceiling + warm-up already exclude the sensory-void case. |
| `warmup_observations` | integer | `200` | Warm-up gate (fail-closed): a crossing does not count until at least this many logged lived events (cycle ticks) have accumulated. Mirrors `[evaluation.individuation].min_observations` so the live trigger and the decommission gate agree. |
| `warmup_lived_time_s` | float | `1800.0` | Warm-up gate: at least this much elapsed lived (running) time before a crossing counts. Before the floor is met an assessment is treated as not-crossed and logged as a warming-up note. |
| `out_root` | string | `"backups"` | Directory where preservation bundles are written. |
| `entity_name` | string | `"kaine"` | Entity name stamped into the bundle. |

### `[preservation.welfare_response]`

The autonomous welfare-protective response. Watches the Soma interoceptive-distress signal and, on a sustained-distress crossing, preserves the entity then takes a humane action.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Ships disabled. |
| `poll_interval_s` | float | `1.0` | Poll cadence for draining `soma.out`. |
| `action` | string | `"pause"` | `"pause"` (preserve then freeze the cycle, resumable), `"end"` (preserve then signal the run to stop), or `"notify"` (preserve, record, continue). |
| `distress_threshold` | float | `0.8` | `prediction_error` magnitude at/above which distress is counted. |
| `distress_duration_s` | float | `30.0` | Continuous sustain required before the action fires. |
| `repeat_window_s` | float | `300.0` | Window for the repeated-episodes arm. |
| `repeat_threshold` | integer | `3` | Sustained episodes within `repeat_window_s` that also cross the threshold. |
| `warmup_s` | float | `120.0` | Cold-start warm-up: during the first `warmup_s` after run start, gray-zone / distress events are observed and logged but do not count toward the repeat threshold or trigger the preserve-then-act response. Stops boot transients (distress before homeostatic setpoints settle) from being mistaken for sustained welfare problems; both arms function unchanged after the window. |
| `out_root` | string | `"backups"` | Directory where preservation bundles are written. |
| `entity_name` | string | `"kaine"` | Entity name stamped into the bundle. |

### `[preservation.retention]`

Preservation-bundle retention. Distinct from the 64-snapshot fork cap: a preserved individual must never be silently auto-evicted (CAL Article 4.2/4.3).

| Key | Type | Default | Description |
|---|---|---|---|
| `auto_evict` | boolean | `false` | Ships `false`. Setting it `true` is refused at boot — preservation bundles are retained indefinitely. |

---

## `[research]`

Unsupervised-research boot mode. When enabled (or `KAINE_RESEARCH_MODE=1`), the operator-present requirement is replaced by the safety-net-present gate (see [Research boot gate](operations.md#research-boot-gate-safety-net-present-replacing-operator-present)). Ships disabled.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | When true, the boot refuses to start (exit code `5`, operator-facing message, no traceback) unless preservation is enabled, the welfare-protective response is wired, logging/admissibility is active, and a dry `preserve→revive` self-check passes. A run is either operator-present or research-safety-net-verified, never neither. |

---

## `[nexus]`

Web UI server. Provides the operator **console** (`/`), **diagnostics**
(`/diagnostics/`, also a settings popup over the console), and **evaluation**
(`/diagnostics/evaluation/`) surfaces, with a structural privacy boundary:
diagnostics show operational metadata only (counts, rates, salience, affect
dimensions) and never cognitive content unless `dev_content_override = true`. The
console and evaluation surfaces show no message content.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Bind address. Loopback-only by default. |
| `port` | integer | `8088` | HTTP port. |
| `conversation_enabled` | boolean | `true` | Enable the console surface at `/` (the route is internally named *conversation*). |
| `diagnostics_enabled` | boolean | `true` | Enable the diagnostics surface. |
| `conversation_history_lookback` | integer | `50` | History lookback for the `/` route. The console renders no transcript, so this only bounds the (now unused) backfill — a remnant of the removed conversation panel. |
| `dev_content_override` | boolean | `false` | When true, the diagnostics surface includes raw content (message text, beliefs, memory bodies, internal speech, affect reasons) and displays a "dev mode" banner. Keep `false` in production. |

---

## `[security.state_encryption]`

Application-layer AES-256-GCM encryption-at-rest for persisted cognitive state (Eidolon self-model, fork/merge snapshot bundles, sidecar observer JSONL, Phantasia world-model checkpoints when the real backend writes them). Ships disabled.

**Two-layer gate:** `enabled = true` *and* a 32-byte key must be available (fail-closed). With `enabled = true` but no key, the entity refuses to boot.

**Key resolution order:**
1. Environment variable named by `key_env_var` (default `KAINE_STATE_KEY`).
2. Linux kernel keyring (`user` keyring, description `kaine:state_key`).

The key is never hardcoded, logged, or persisted. Supply 32 raw bytes, or base64/hex encoding of 32 bytes.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `key_env_var` | string | `"KAINE_STATE_KEY"` | Environment variable name holding the AES-256 key. |
| `algorithm` | string | `"aes-256-gcm"` | Encryption algorithm. Only `"aes-256-gcm"` is supported; any other value raises `CryptoConfigError` at boot. |

On-disk framing: `KAINE_MAGIC || nonce(12 bytes) || ciphertext+tag`, base64-encoded. The magic prefix lets the reader distinguish encrypted blobs from legacy plaintext, so a disabled reader transparently passes plaintext through.

---

## `[transfer]`

Operator-configured SMTP coordination for the welfare-gated decommission workflow (see `python -m kaine.lifecycle`). When an individuated entity is decommissioned the operator may request the project to safekeep the encrypted backup. This section controls how that request email is sent.

**Ships inert.** With `enabled = false` or any required field blank the decommission CLI writes a `transfer_request.eml` and a `mailto:` link for the operator to send manually. SMTP is never used without `enabled = true` *and* a complete configuration.

**Privacy invariant (CAL 4.3):** the request email carries only the situation and the *local filesystem path* of the encrypted backup — never any entity content.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. When false the CLI falls back to `.eml` write + mailto link. |
| `smtp_host` | string | `""` | SMTP server hostname. |
| `smtp_port` | integer | `587` | SMTP server port (STARTTLS). |
| `smtp_user` | string | `""` | SMTP username for authentication. |
| `from_addr` | string | `""` | Sender address for the request email. |
| `recipient` | string | `""` | Address the request is sent to. Suggested default: `kaine.one@tuta.com` (project guardians). If left empty the CLI prompts and requires explicit confirmation. |

**Password:** the SMTP password is read exclusively from the environment variable `KAINE_SMTP_PASSWORD` — never from this file, never logged.

---

## `[research_submission]`

Opt-in, operator-initiated research data submission. All transmissions require explicit operator confirmation. Nothing is sent automatically.

The default bundle (`tier = "metrics"`) is numeric metrics only and never contains speech, transcripts, the Lingua intent log, Mnemos memories, the Eidolon self-model, or any conversation content. Run `python -m kaine.research --preview` to inspect the bundle before sending; `--send` to submit. Submission reuses the `[transfer]` SMTP settings for the notification email.

See [docs/research-participation.md](research-participation.md) for the full privacy inventory and send procedure.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. When false `--send` is blocked; `--preview` always works regardless. |
| `recipient` | string | `""` | Recipient for the bundle notification email. If empty the CLI suggests `kaine.one@tuta.com` and requires explicit operator confirmation before sending. |
| `tier` | string | `"metrics"` | Bundle tier. `"metrics"` (numeric metrics only, no content) is the only tier available without additional opt-in attestation. |

Admissibility enforcement (paper §6.3) is code-side, not config-side: every bundle build auto-discovers the run(s) in the eval logs and runs both a completeness gate (contiguous ticks/seq, all expected streams present, no parse errors, no restart/multi-process signature) and a log-range sweep (every logged number within its declared range), blocking the export by default if either check fails. The only way to export an inadmissible run is the explicit `admissibility_override=True` + a reason string at the call site (CLI: `--admissibility-override-reason "<why>"`), which is stamped into the bundle manifest.

---

## `[research_event_log]`

Curated, privacy-filtered research event log for longitudinal analysis. Subscribes to a curated allowlist of bus streams and writes one privacy-filtered record per relevant event (numeric/categorical fields only) to an encrypted, daily-rotated JSONL sink under `data/evaluation/research_events/`. Every record passes the `PrivacyFilter` (strips text/content/transcription/etc.) plus per-type redaction BEFORE write — it never captures raw audio/video, transcripts, conversation content, memory text, the Eidolon self-model, or operator host/IP. Avatar coordinates are logged only as an opaque hash.

`research_events` is in the metrics-bundle allowlist (`METRICS_ONLY_DIRS`), so an operator-initiated metrics research bundle may include it — this section is the only mechanism that makes it export-eligible.

Ships disabled. Independent of `[evaluation].enabled` — this runs on its own flag even when the evaluation sidecar is off (and vice-versa).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `log_dir` | string | `"data/evaluation/research_events"` | Directory for the curated log sink. Must stay under `data/evaluation/` to remain export-eligible. |
| `retention_days` | integer | `30` | Daily-rotated file retention window (days). |

### `[research_event_log.raw_archive]`

Optional, local-only raw bus archive. Never export-eligible. Tees VERBATIM bus events (including conversation content and transcripts) to `state/research/raw_bus_archive/` — a path outside `data/evaluation/`, so the metrics bundle builder can never reach it. Encrypted at rest like every sink.

**Doubly gated:** requires `enabled = true` AND both attestation flags `true`. With `enabled = true` but either attestation false, the consumer refuses to start (`RawArchiveAttestationError`, logged as an error) — mirroring the full-tier attestation gate in `kaine/research/submission.py`.

Ships disabled. Set all three flags true only after confirming entity privacy and bystander consent for verbatim local capture.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Ships disabled. |
| `entity_privacy_attested` | boolean | `false` | Attestation: entity privacy considerations reviewed. Required alongside `bystander_consent_attested` for the archive to start. |
| `bystander_consent_attested` | boolean | `false` | Attestation: bystander consent for verbatim local capture obtained. Required alongside `entity_privacy_attested` for the archive to start. |
| `archive_dir` | string | `"state/research/raw_bus_archive"` | Storage path. Must remain outside `data/evaluation/`. |
| `retention_days` | integer | `30` | Daily-rotated file retention window (days). |

---

## `[logging]`

| Key | Type | Default | Description |
|---|---|---|---|
| `level` | string | `"INFO"` | Python logging level. Valid values: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"`. |

---

## `[mundus]`

Body-agnostic embodiment control plane. Mundus routes perception and action to and from a *body* through a pluggable adapter selected here; adapter-specific settings live under `[mundus.<adapter>]`. Enabled via the three-layer gate: `[modules].mundus = true` (module toggle) AND `[mundus].enabled = true` (config layer) AND the environment variable `KAINE_MUNDUS_OPERATOR_APPROVED=1` (operator layer). All three must be true before any action reaches the body. Per-family and per-channel exposure flags additionally gate world-mutating verbs and continuous channels.

The shipped default is the transport-free `stub` reference body, which needs no configuration. No transport-backed body ships today; a virtual-world (Paracosmic) adapter is planned, and its settings will live under its own `[mundus.<adapter>]` table.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Config-layer gate (the module-level toggle `[modules].mundus` is the first gate; this is the second, and `KAINE_MUNDUS_OPERATOR_APPROVED=1` is the third). |
| `adapter` | string | `"stub"` | Which body to construct. Only this adapter is built, from its `[mundus.<adapter>]` table (the stub needs none); an unknown name fails closed at boot. |
| `mirror_speech` | boolean | `true` | Forward Lingua external speech to the body as local-chat `say` actions. |
| `speech_stream` | string | `"lingua.external"` | Bus stream Mundus subscribes to for speech to mirror. |

---

## `[perception]`

Perception locus arbiter (physical-XOR-virtual sense gating). Enabled via `[modules].perception`. When the entity is embodied in a virtual world its physical camera/mic are inhibited, and vice-versa.

| Key | Type | Default | Description |
|---|---|---|---|
| `allow_self_switch` | boolean | `false` | Allow the entity to switch its own perceptual locus via `praxis` intents. Off by default — locus changes are operator-driven until trust is established. Reserved for deferred virtual-world embodiment work; no module currently produces `intent.perception.switch`, so this flag has no effect yet. |
| `min_dwell_s` | float | `30.0` | Minimum seconds the locus must hold before another switch is honoured. |

---

## `[perception_preview]`

Live perception PREVIEW bridge (explicit development override). When — and ONLY when — the operator exports `KAINE_PERCEPTION_PREVIEW=1` in BOTH the cycle process AND the Nexus process, the cycle starts a tiny preview server bound to `127.0.0.1` ONLY that serves the single most-recent in-RAM frame (JPEG) and current audio level to Nexus's picture-in-picture. Frames NEVER touch the filesystem — the bridge is a loopback socket over an in-memory slot, so the zero-raw-sense-persistence invariant holds. Default (flag unset) means nothing binds, the metadata-only boundary is intact, and the PiP stays hidden.

| Key | Type | Default | Description |
|---|---|---|---|
| `port` | integer | `8089` | Loopback port the cycle serves the preview on and Nexus proxies to. |

---

## Secrets file (`config/secrets.toml`)

`config/secrets.toml` is gitignored. Copy `config/secrets.example.toml` to `config/secrets.toml` and fill in the real values (permissions: `chmod 600 config/secrets.toml`).

Environment variables override this file:

| Env var | Overrides |
|---|---|
| `KAINE_REDIS_URL` | Full `redis://` URL including auth |
| `KAINE_REDIS_PASSWORD` | Redis password only |
| `KAINE_REDIS_USERNAME` | Redis username (ACL setups) |
| `KAINE_QDRANT_API_KEY` | Qdrant API key |

### `[redis]` (secrets)

| Key | Purpose |
|---|---|
| `password` | Redis authentication password. Generate with `openssl rand -hex 32`. Must match `compose/.env`. |
| `username` | Redis username (optional; only needed for ACL setups). |
| `url` | Full `redis://<user>:<password>@host:port/db` URL (optional alternative to individual fields). |

### `[qdrant]` (secrets)

| Key | Purpose |
|---|---|
| `api_key` | Qdrant API key. Generate with `openssl rand -hex 32`. Must match `compose/.env`. Required by Mnemos and Empatheia when `backend = "qdrant"`. |

Real secret values are never printed in documentation or committed to the repository.
