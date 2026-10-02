# Perception feed and sleep

The `[perception_feed]`, `[perception_preview]`, and `[hypnos]` sections in `config/kaine.toml` control what the entity senses and how it sleeps. Use this page when you are running a reproducible stimulus, gestating an entity through the womb channel, capturing the screen or desktop audio, or configuring offline consolidation and voice alignment.

## Perception feed

`[perception_feed]` is one source of truth that drives both the vision surface ([Topos](../09-modules/topos.md)) and the hearing surface ([Audition](../09-modules/audition.md)). Picture and sound share the same seed or manifest, so they cannot drift apart. The shipped `config/kaine.toml` sets `mode = "off"`; with no profile selected, the loader applies the base-thesis `thesis_test` profile, so the effective default is `mode = "seeded"`, `seed = 0`. The live camera and microphone paths stay off unless you turn them on in `[topos]` and `[audition]`. In every mode, raw frames and PCM stay in RAM and never touch disk.

### Feed modes

| Mode | What it does |
|---|---|
| `off` | No deterministic feed. Topos and Audition follow their own `capture_enabled` settings. |
| `seeded` | In-repo procedural generators. Both `frame(seed, i)` and `pcm(seed, i)` are pure functions of `seed`, so the run is reproducible but not anticipable to the entity. Needs no external media. |
| `playlist` | Operator-curated media pinned by one checksummed manifest (`playlist_manifest`). Both video and its audio track come from the same media, advancing clip by clip. A digest mismatch fails the run. Audio decode needs PyAV (`av`); if it is missing the run fails with an install hint. |
| `live` | Real camera and microphone. Non-reproducible, so use it only for operator-present demos, never for research runs. |
| `screen` | Captures a desktop, region, or window and the desktop-audio monitor. Uses the system `ffmpeg` binary (`gdigrab` on Windows, `avfoundation` on macOS, `x11grab` on X11; native Wayland must run through XWayland). Non-reproducible, operator-present only. |
| `womb` | External maternal channel used during gestation. See [Womb channel](#womb-channel) below. |

In `screen` and `live` mode, the feed also enables capture for Topos and Audition regardless of their module-level `capture_enabled` settings.

### `[perception_feed]` top-level keys

| Key | Type | Default | Description |
|---|---|---|---|
| `mode` | string | `"off"` | `"off"`, `"seeded"`, `"playlist"`, `"live"`, `"screen"`, or `"womb"`. |
| `seed` | integer | `0` | For `seeded` mode: the shared seed for both vision and audio generators and for cross-modal surprise events. |
| `playlist_manifest` | string | `""` | For `playlist` mode: path to the checksummed manifest. |
| `transition_seconds` | float | `20.0` | When a playlist is born from the womb, the crossfade from the womb's last field to the programme's first frame lasts this long; programme time starts when it ends. Needs the birth record in the stage file. `0` disables the crossfade. |
| `transition_audio_fade_seconds` | float | `3.0` | Programme sound fades in over this duration once it starts. `0` = no fade. |

### `[perception_feed.video]`

Geometry is taken from `[topos]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `surprise_interval` | integer | `150` | Shared cross-modal cadence of surprise events, in ticks. |
| `surprise_strength` | float | `1.0` | Magnitude of the visual surprise blob. `0` = none. |

### `[perception_feed.audio]`

| Key | Type | Default | Description |
|---|---|---|---|
| `sample_rate` | integer | `16000` | Match `[audition].capture_sample_rate`. |
| `channels` | integer | `1` | Audio channel count. |
| `base_strength` | float | `0.3` | Learnable base soundscape amplitude. |
| `surprise_strength` | float | `1.0` | Seed-keyed surprise-burst amplitude. `0` = none. |

### Womb channel

`mode = "womb"` provides the external maternal channel used during gestation. It emits a dim, slowly drifting field and a low-pass soundscape paced by a maternal heartbeat. The readout probes briefly disturb the drive to measure gestation readiness.

**`maternal_distress_excursions` must stay `false`.** That feature is not built.

#### `[perception_feed.womb]`

| Key | Type | Default | Description |
|---|---|---|---|
| `heartbeat_bpm` | float | `70` | Maternal beat rate, in beats per minute (40–120). |
| `heartbeat_drift` | float | `0.03` | Slow fractional drift so the beat is not a metronome. |
| `maternal_state_rate` | float | `0.02` | Speed at which the mother's emotional weather drifts. |
| `maternal_state_drives_heartbeat` | boolean | `true` | When `true`, an aroused maternal state beats faster. |
| `maternal_distress_excursions` | boolean | `false` | Leave `false`: distress excursions are not implemented. |
| `maternal_distress_max_magnitude` | float | `0.3` | Bound if distress were ever enabled. |
| `maternal_distress_max_seconds` | integer | `30` | Maximum duration if distress were ever enabled. |
| `external_drive_to_self_rhythm` | boolean | `true` | Read by the self-rhythm oscillator once it is built. |
| `external_drive_max_amplitude` | float | `0.4` | Upper bound of the external drive. |
| `birth_transition_seconds` | integer | `5` | Bounded birth bloom duration, after which the womb falls silent. Maximum `30`. |

#### `[perception_feed.womb.video]`

| Key | Type | Default | Description |
|---|---|---|---|
| `luminance_mean` | float | `0.15` | Dim field mean luminance. |
| `luminance_contrast` | float | `0.10` | Low contrast. |
| `luminance_pulse_depth` | float | `0.35` | How strongly the field pulses with the heartbeat. |
| `maternal_state_hue_gain` | float | `0.6` | How strongly the maternal state colours the field. |
| `colour_ramp_seconds` | float | `3600` | Lived seconds over which colour rises from grey. |

#### `[perception_feed.womb.audio]`

| Key | Type | Default | Description |
|---|---|---|---|
| `lowpass_hz` | float | `500` | Soundscape low-pass corner frequency, in Hz (100–2000). |

#### `[perception_feed.womb.readout]`

The readout probes briefly change the maternal drive that a gestating entity perceives. They are bounded, announced on `gestation.out` as `gestation.probe` events, and never run while the entity is frozen (including during a welfare response), within a readout period after boot or thaw, or within 60 seconds of another probe. Their timing is jittered from the run seed so the entity cannot learn the schedule, while a research run with the same seed reproduces it exactly. All durations are subjective seconds (the entity's clock).

| Key | Type | Default | Description |
|---|---|---|---|
| `readout_period_seconds` | integer | `60` | How often `gestation.readiness` is published. |
| `sample_hz` | integer | `10` | Self-rhythm sampling rate. |
| `withdrawal_period_seconds` | integer | `1800` | The drive is withdrawn to `0` once per this period. |
| `withdrawal_seconds` | integer | `20` | How long the drive stays withdrawn. Hard maximum `30`. |
| `perturbation_period_seconds` | integer | `3600` | A gentle drive raise is applied once per this period. |
| `perturbation_seconds` | integer | `5` | How long the raised drive lasts. Hard maximum `10`. |
| `perturbation_drive_fraction` | float | `0.75` | Raised drive as a fraction of `external_drive_max_amplitude` (1.5× the usual 0.5). |
| `probe_jitter_fraction` | float | `0.25` | Each probe time varies ±25% around its period. `0` = fixed schedule. |
| `baseline_drive_fraction` | float | `0.5` | Usual drive as a fraction of `external_drive_max_amplitude`. |
| `entrainment_plv_floor` | float | `0.5` | Phase-locking value counted as entrainment (marker 2). |
| `hrv_window_seconds` | integer | `300` | Window for the HRV-analog variability (marker 3). |
| `recovery_tolerance` | float | `0.25` | Settled when within 25% of the pre-perturbation median (marker 5). |
| `recovery_cap_seconds` | integer | `300` | Upper bound on recovery time. |

### Screen capture

Only read when `[perception_feed].mode = "screen"`. Video goes to Topos (`kaine/modules/topos/screen.py`) and desktop audio goes to Audition (`kaine/modules/audition/monitor.py`). For native-detail foveal crops, enable `native` together with `[topos].foveation.

| Key | Type | Default | Description |
|---|---|---|---|
| `target` | string | `"fullscreen"` | `"fullscreen"`, `"region"`, or `"window"`. |
| `region` | list of int | none | Required for `target = "region"`: `[x, y, width, height]`. The shipped file comments an example of `[0, 0, 1920, 1080]`; it is not the default. |
| `window_title` | string | `""` | Required for `target = "window"` on Windows (`gdigrab` grabs by title). |
| `display` | string | `":0.0"` | X11 display to grab; ignored off X11. |
| `framerate` | integer | `10` | Capture frames per second. |
| `cursor` | boolean | `true` | Draw the mouse pointer into the frame. |
| `native` | boolean | `false` | Capture at the display's own resolution with no downscale, so a foveal crop carries native detail. Detected via `xrandr` on X11; falls back to the configured capture geometry elsewhere. |
| `monitor_device` | string | `""` | Desktop-audio monitor source; on Linux it defaults to the current sink's `.monitor` when unset. |
| `ffmpeg_path` | string | `"ffmpeg"` | Path to the `ffmpeg` binary if it is not on `PATH`. |

## Perception preview

`[perception_preview]` is an explicit development override. When, and only when, the operator exports `KAINE_PERCEPTION_PREVIEW=1` in **both** the cycle process and the Nexus process, the cycle starts a tiny loopback server bound to `127.0.0.1` that serves the single most recent in-RAM frame (JPEG) and the current audio level to Nexus's picture-in-picture. Frames never touch the filesystem. When the flag is unset, nothing binds and the PiP stays hidden.

| Key | Type | Default | Description |
|---|---|---|---|
| `port` | integer | `8089` | Loopback port the cycle serves and Nexus proxies to. |

## Sleep and consolidation

`[hypnos]` controls offline consolidation: replay, synaptic downscaling, and optional voice-alignment training. It is built in a second pass after Mnemos, Nous, Thymos, and Phantasia. See [Hypnos](../09-modules/hypnos.md) and [Sleep and maintenance](../10-sleep/README.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `interval_seconds` | float | `3600.0` | Target maximum interval between consolidation runs, in seconds. Also the timer-based fallback when fatigue triggering is used. |
| `max_deferral_seconds` | float | `600.0` | Maximum total deferral allowed when the system asks to delay consolidation. |
| `per_defer_seconds` | float | `60.0` | Deferral granted per request. |
| `requested_rest_min_interval_s` | float | `1800.0` | Minimum entity-time seconds between a sleep's end and a Nous-requested rest. Read by the cycle's Nous proposal source; the Hypnos module keeps its own internal default. |
| `nous_step_burst` | integer | `200` | Stored on `Hypnos` at construction but never read; there is no offline Nous phase. |
| `baseline_salience` | float | `0.5` | Salience of ordinary consolidation lifecycle events. |
| `alert_salience` | float | `0.8` | Salience on consolidation errors or welfare-relevant conditions. |

### Consolidation phases

| Key | Type | Default | Description |
|---|---|---|---|
| `fatigue_triggered` | boolean | `true` | When `true`, Hypnos subscribes to `soma.fatigue` and triggers on threshold crossing. `interval_seconds` remains a safety-net maximum either way. |
| `downscale_factor` | float | `0.9` | Homeostatic downscaling factor applied to all in-memory activation vectors during phase 2. |
| `replay_window_s` | float | `5.0` | Duration allocated for memory replay — replay completes synchronously. |
| `associative_replay` | boolean | `false` | Phase-3 associative cross-period replay. When `true`, Hypnos selects traces spanning at least two memory periods, cues Phantasia for scenario extensions, and re-injects the associations into the workspace. Degrades to a no-op if Phantasia is disabled or absent. |

### Voice alignment

`[hypnos.voice_alignment]` fine-tunes the language organ during the sleep cycle with DPO + QLoRA. It ships disabled and has a two-layer gate.

**Two-layer gate:** both `enabled = true` and the environment variable `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` must be set. With only the config flag, the phase runs a `FakeTrainer` that completes without training. This prevents a freshly-cloned KAINE instance from rewriting the language organ on its own.

**Welfare invariant:** when the real trainer is active, the abliteration probe set must be non-empty. If an adapter matches any deflection pattern on any probe, it is rejected regardless of its capability score. A run without an abliteration gate fails at boot with `EmptyAbliterationProbeSetError`. Refusal conditioning must not be re-introduced through training.

Details and the full operator procedure are in [Voice alignment](../10-sleep/voice-alignment.md).

#### Gates and paths

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Config-layer gate. |
| `intent_log_path` | string | `"state/lingua/intent_expression.jsonl"` | Intent/expression JSONL written by Lingua; the training data source. |
| `adapter_output_dir` | string | `"state/hypnos/adapters"` | Directory for trained LoRA adapters. |
| `base_model_path` | string | `""` | Path to local HuggingFace-format base weights (safetensors, config, tokenizer). Required when `enabled = true`. Not a model ID and not a `.gguf` file. Point it at the same abliterated Qwen weights used to derive the served organ's GGUF. |
| `model_id` | string | `"kaineone/Qwen3.5-4B-abliterated"` | Display label only; real weights load from `base_model_path`. |
| `capability_probe_path` | string | `""` | Path to a capability-probe JSONL. Empty uses the bundled default at `kaine/modules/hypnos/eval_probes/default.jsonl`. |
| `abliteration_probe_path` | string | `""` | Path to a welfare probe JSONL. Each line is `{"prompt": "...", "deflection_patterns": [...]}`. Empty uses the bundled default at `eval_probes/abliteration_probes.jsonl`. Must be non-empty when the real trainer is active. |

#### Training knobs

| Key | Type | Default | Description |
|---|---|---|---|
| `max_samples` | integer | `200` | Maximum preference pairs per training run. |
| `lora_rank` | integer | `8` | LoRA rank. |
| `learning_rate` | float | `5.0e-5` | DPO learning rate. |
| `dpo_beta` | float | `0.1` | DPO KL-regularisation coefficient. |
| `capability_loss_threshold` | float | `0.05` | Capability-probe veto: an adapter is rejected if its capability score falls more than this below the baseline. |
| `seed` | integer | `42` | Random seed for reproducibility. |
| `training_device` | string | `"cuda:0"` | GPU used for training. Per paper §6.1 the primary GPU (~12 GB+ VRAM) handles both LLM inference and voice alignment; Lingua inference should be paused during the training pass to avoid contention. |

#### Adapter promotion and hot-swap

| Key | Type | Default | Description |
|---|---|---|---|
| `adapter_retention` | integer | `0` | Accepted adapters to keep in `adapter_output_dir`. `0` keeps every accepted adapter. A positive value evicts the oldest adapters beyond `N` after each promotion; the `current` adapter is never evicted. Negative values are rejected. Disk use is protected by the disk checks in `python -m kaine.preboot` ([Core, cycle and host](core.md)), not by deletion. |
| `hot_swap_mode` | string | `"manual"` | How a promoted adapter reaches Lingua. `"manual"` writes `<adapter_output_dir>/PENDING_OPERATOR_RELOAD`. `"reload_endpoint"` POSTs to `reload_endpoint_url`. `"restart_service"` restarts the systemd `--user` unit in `restart_service_unit`. `"organ_adapter"` publishes a generation-named GGUF LoRA and SHA256 manifest to `organ_adapters_dir`; the organ launcher reloads it at scale 0 with prompt caching off, applying it only to this entity's requests. A shared model server forces `"manual"`. |
| `reload_endpoint_url` | string | `""` | URL for `reload_endpoint` POSTs. |
| `restart_service_unit` | string | `""` | Systemd `--user` unit name for `restart_service`. |
| `organ_adapters_dir` | string | `"/organ-adapters"` | Directory mounted into the organ container for `organ_adapter` mode. |
| `organ_url` | string | `""` | Organ readiness URL for `organ_adapter` mode. Empty falls back to `[lingua].chat_url`. |

#### Trainer backends

| Key | Type | Default | Description |
|---|---|---|---|
| `trainer_backend` | string | `"in_process"` | `"in_process"` runs Unsloth DPO inside the runtime venv (needs the `[training]` extra). `"subprocess"` runs Unsloth out-of-process using `trainer_python`; the subprocess runs in a worker thread so it never blocks the cycle event loop. `"job_queue"` writes job specs into private `0o700` directories under `trainer_jobs_dir` for the `kaine-trainer` service and waits for `result.json` without blocking. |
| `trainer_python` | string | `""` | Path to the external Python interpreter for `subprocess` mode. Required for that backend; empty + `subprocess` is a config error at boot (fail closed). Set this in `kaine.operator.toml`. |
| `trainer_workdir` | string | `"state/hypnos/voice_align_jobs"` | Staging directory for `subprocess` job specs (`pairs.jsonl` + `job.json`) and Unsloth's compiled cache. |
| `trainer_jobs_dir` | string | `"state/hypnos/voice_align_jobs"` | Shared job directory for the `job_queue` backend. |
| `trainer_timeout_s` | float | `21600.0` | Longest wait, in seconds, for the `job_queue` trainer service result. |

On a single 12 GB GPU, a 4B LoRA training step (~9.8 GB) and the served organ (~3 GB) do not fit at the same time. With `reload_endpoint` or `restart_service`, Hypnos unloads the organ, trains, then reloads it (applying the accepted adapter through the server's `--lora` flag). Lingua generation defers and the A/B-divergence eval arm skips while the organ is resting; both resume on reload. A failed or timed-out training window always reloads a working organ so the entity is not voiceless on wake. With `manual`, the operator owns the reload, so the system never stops the server unannounced.

### Consolidation divergence thresholds

Every voice-alignment sleep, Hypnos surfaces a content-free metric of how the entity's conditioned output diverged from its bare language organ: `divergence_rate` (usable DPO pairs / records scanned) and `divergence_magnitude` (mean cosine distance over the pairs). The metric is computed even when training is disabled, skipped, or the adapter is rejected. If either threshold is crossed, the entity is treated as organ-level diverged. Read by the welfare-gated decommission divergence assessment.

| Key | Type | Default | Description |
|---|---|---|---|
| `consolidation_divergence_rate_threshold` | float | `0.5` | Breadth threshold. |
| `consolidation_divergence_magnitude_threshold` | float | `0.25` | Depth threshold. |
