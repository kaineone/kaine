# Modules

This page documents every module-specific configuration section in `config/kaine.toml`. Use it when enabling a module in the `[modules]` table (see [Core, cycle and host](core.md)) and tuning its behavior. For the perception feed, sleep, and voice alignment settings see [Perception feed and sleep](perception-and-sleep.md); for lifecycle and research settings see [Lifecycle, evaluation and research](lifecycle-and-research.md); for security and Nexus see [Security and Nexus](security-and-nexus.md).

## Soma

Section: `[soma]`.

Soma is the predictive interoception module. It reads CPU, RAM, GPU, and cycle-latency metrics, runs a small forward model, and publishes prediction errors that influence the workspace. See [The Soma module](../09-modules/soma.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `cfc_backend` | string | `"numpy"` | `"numpy"` needs no torch; `"torch"` uses `ncps` and needs the `core` extra. Both build the same seeded reservoir, whose seed is kept in Soma's snapshot. |
| `read_interval_s` | float | `1.0` | Seconds between substrate metric reads. |
| `cycle_latency_target_ms` | float | `300.0` | Target cognitive-cycle latency; deviation drives prediction error. |
| `cycle_latency_window` | integer | `64` | Rolling-window size for cycle-latency averaging. Passed through to the reader. |
| `baseline_salience` | float | `0.1` | Salience when substrate metrics are within normal bounds. |
| `alert_salience` | float | `0.7` | Salience on threshold breach or sustained high unexpected prediction error. |
| `forward_model_units` | integer | `32` | Hidden units of the CfC interoceptive forward model. |
| `prediction_error_window` | integer | `32` | Rolling-window size (ticks) for normalizing the prediction error signal. |
| `fatigue_decay_per_s` | float | `0.01` | Rate at which the fatigue accumulator decays per second under low load. |
| `fatigue_maintenance_threshold` | float | `100.0` | Fatigue value that triggers a Hypnos consolidation request. |
| `regulation_sustain_window_s` | float | `30.0` | Minimum window of sustained high unexpected error before regulation requests are emitted. |
| `regulation_threshold` | float | `0.5` | Unexpected prediction-error level at which sustained regulation is considered. |
| `expected_error_tau_s` | float | `600.0` | Time constant, in subjective seconds, for the per-channel running average of absolute prediction error and its spread. |
| `expected_error_band` | float | `2.0` | Spread widths above the expected absolute error that are treated as unsurprising. |
| `regulation_warmup_enabled` | boolean | `true` | Withholds punitive allostatic actions while the forward model learns this host's substrate baseline. |
| `regulation_warmup_min_samples` | integer | `1000` | Minimum adaptation samples before warm-up can end. |
| `regulation_warmup_min_seconds` | float | `1200.0` | Minimum lived subjective seconds before warm-up can end. |
| `regulation_warmup_require_error_stabilized` | boolean | `false` | Optional extra guard: also require prediction-error variance to fall below `regulation_warmup_stable_variance`. Can only extend warm-up. |
| `regulation_warmup_stable_window` | integer | `32` | Rolling window used for the optional stability check. |
| `regulation_warmup_stable_variance` | float | `0.02` | Variance bound for the optional stability check. |
| `self_rhythm_enabled` | boolean | `false` | Enable the self-rhythm Soma hosts: a breathing-like mean-field rhythm generator read out by 16 LIF units. Required for local gestation; needs the oscillator extra. |
| `self_rhythm_step_hz` | float | `20.0` | Subjective-time cadence the self-rhythm integrates at. |
| `self_rhythm_eta` | float | `0.0025` | Rate at which the self-rhythm's period adapts to its input. Calibrated so an earned lock to the maternal beat typically forms within the gestation budget. `0` disables adaptation, so entrainment can never be earned. |

Warm-up does **not** gate the absolute thresholds in `[soma.thresholds]`. A real substrate breach (for example, GPU temperature ≥ 83 °C) overrides warm-up and actuates at full weight.

### Thresholds

Section: `[soma.thresholds]`.

| Key | Default | Description |
|---|---|---|
| `"cpu_percent"` | `90.0` | CPU utilization alert threshold (percent). |
| `"ram_percent"` | `90.0` | RAM utilization alert threshold (percent). |
| `"gpu_*_temp_c"` | `83.0` | GPU temperature alert threshold (degrees Celsius). Glob matches all GPU indices. |
| `"gpu_*_vram_percent"` | `92.0` | GPU VRAM utilization alert threshold (percent). |
| `"cycle_latency_avg_ms"` | `600.0` | Cycle-latency alert threshold (milliseconds). |

### Weights

Section: `[soma.weights]`.

| Key | Default | Description |
|---|---|---|
| `"cpu_percent"` | `1.0` | Weight for the CPU error term. |
| `"ram_percent"` | `1.0` | Weight for the RAM error term. |
| `"cycle_latency_avg_ms"` | `1.0` | Weight for the cycle-latency error term. |

## Chronos

Section: `[chronos]`.

Chronos models event rhythm across the bus with a small CfC network and publishes timing anomalies, habituation, and rumination events. See [The Chronos module](../09-modules/chronos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `cfc_backend` | string | `"numpy"` | `"numpy"` needs no torch; `"torch"` uses `ncps` and needs the `core` extra. Both build the same seeded reservoir, whose seed is kept in Chronos's snapshot. |
| `cfc_units` | integer | `32` | Hidden units in the CfC temporal network. |
| `baseline_salience` | float | `0.1` | Salience when timing is within expected bounds. |
| `alert_salience` | float | `0.7` | Salience on anomaly, habituation, or rumination detection. |
| `anomaly_window` | integer | `64` | Rolling-window length (ticks) passed to the Chronos constructor for the anomaly detector. |
| `anomaly_alert_threshold` | float | `3.0` | Z-score above which an inter-event interval is flagged as anomalous. |
| `rumination_window` | integer | `32` | Rolling window (ticks) for detecting repeated event types. |
| `rumination_threshold` | integer | `4` | Count of the same event type within `rumination_window` that triggers a rumination alert. |
| `rumination_bucket_resolution` | float | `0.25` | Bucket width (seconds) for discretizing event timestamps in the rumination detector. |
| `user_input_streams` | list of strings | `["audition.out"]` | Streams Chronos monitors for user-input timing. |
| `interaction_event_types` | list of strings | `["audition.transcription", "audition.emotion"]` | Event types on those streams that count as an interaction when they come from an operator channel. |
| `forward_prediction` | boolean | `false` | Enable the forward-model prediction head. Disabled by default in the shipped file; enabled in the default `thesis_test` profile. |
| `prediction_error_window` | integer | `32` | Rolling-window size (ticks) for normalizing the temporal prediction error signal. |

## Topos

Section: `[topos]`.

Topos is the vision module. It embeds short video clips into a motion-aware latent using a frozen encoder, predicts the next latent with a shallow forward model, and drives workspace salience from prediction error. Raw camera frames live in a RAM-only ring buffer and never touch disk. See [The Topos module](../09-modules/topos.md).

### Encoder setup

| Key | Type | Default | Description |
|---|---|---|---|
| `encoder_backend` | string | `"internvideo_next"` | Encoder selector: `"internvideo_next"` (default, temporally-native clip) or `"dinov2"` (per-frame Apache-2.0 fallback). |
| `encoder_model_id` | string | `"revliter/internvideo_next_base_p14_res224_f16"` | Model ID for the active backend. |
| `encoder_revision` | string | `ff2659b9be360a6b1e94b1eb381778a960da6019` | The pinned InternVideo-Next revision. Any other value refuses boot, because the pin decides which vendored code and weights load. |
| `encoder_local_dir` | string | `"state/models/internvideo_next_base_p14_res224_f16"` | Git-ignored local directory that holds the weights. Runtime loads only from here. |
| `device` | string | `"cuda:1"` | Compute device for the encoder. Accepts `"auto"`, `"cpu"`, `"cuda"`, or `"cuda:N"`. `resolve_device()` falls back to `cuda:0` on single-GPU hosts, then to `cpu` with a logged warning. |

Fetch the InternVideo-Next weights once with:

```bash
python -m kaine.setup.internvideo_next --yes
```

The real encoder needs the `[internvideo]` extra (`einops`, `timm`, `easydict`). The default eager attention path needs no `flash-attn` and no CUDA toolchain. Add the optional `[internvideo-flash]` extra only on a GPU host that wants the fused flash-attn kernels.

### Clip processing

| Key | Type | Default | Description |
|---|---|---|---|
| `clip_len` | integer | `16` | Frames per clip consumed by the encoder. |
| `clip_stride` | integer | `3` | Strided sliding window: one clip latent every N frame-ticks. At the shipped `vision_sample_hz = 10`, this emits roughly 3.33 Hz. |
| `clip_resolution` | integer | `224` | Clip input resolution. |
| `pooling` | string | `"attention"` | Token pooling: `"attention"` (native pool head) or `"mean"`. |
| `change_alert_threshold` | float | `1e-4` | Small absolute noise floor for the change alert. The primary criterion is `change_alert_factor` times the rolling mean. |
| `change_alert_factor` | float | `2.0` | Relative multiplier: a change alerts when it reaches this factor times the rolling-window mean of change scores. |
| `habituation_window` | integer | `16` | Number of recent embeddings the habituator averages over. At least 2. |
| `baseline_salience` | float | `0.2` | Salience during expected visual state. |
| `alert_salience` | float | `0.7` | Salience on unexpected visual change. |

### Live camera

| Key | Type | Default | Description |
|---|---|---|---|
| `capture_enabled` | boolean | `false` | Enable the live camera. Requires the `[vision]` extra. Raw frames stay in memory. |
| `capture_device` | integer or string | `0` | `cv2.VideoCapture` device index or URL. |
| `capture_interval_s` | float | `0.1` | Seconds between camera captures, kept consistent with `vision_sample_hz`. |
| `vision_sample_hz` | float | `10.0` | Authoritative vision-sampling cadence. When both keys are present it overrides `capture_interval_s`. |
| `capture_width` | integer | `640` | Capture frame width in pixels. |
| `capture_height` | integer | `480` | Capture frame height in pixels. |
| `capture_warmup_frames` | integer | `3` | Frames discarded on startup to let the sensor stabilize. |

### Forward model

| Key | Type | Default | Description |
|---|---|---|---|
| `forward_prediction` | boolean | `true` | Enable the visual forward model. The encoder stays frozen; only the MLP trains. |
| `forward_model_units` | integer | `256` | Hidden-layer width of the shallow MLP forward model. |
| `prediction_error_window` | integer | `32` | Rolling-window size (frames) for normalizing the prediction error signal. |
| `visual_buffer_size` | integer | `16` | Number of recent latents kept in the recurrent visual buffer. |

### Foveation

Section: `[topos]` foveation keys.

| Key | Type | Default | Description |
|---|---|---|---|
| `foveation` | boolean | `false` | Master gate for attention-driven foveation. Off by default. |
| `foveation_grid` | list of int | `[12, 12]` | Saliency tiling (rows, cols). |
| `foveation_hysteresis` | float | `0.15` | A new tile must beat the held tile by more than this fraction to move the fovea. |
| `foveation_arousal_size_min` | float | `0.12` | Fovea half-extent fraction at arousal = 1.0 (tightest). |
| `foveation_arousal_size_max` | float | `0.5` | Fovea half-extent fraction at arousal = 0.0 (widest). |
| `peripheral_width` | integer | `320` | Width of the downsampled peripheral gist. |
| `peripheral_height` | integer | `180` | Height of the downsampled peripheral gist. |
| `foveal_size` | integer | `224` | Side length of the square foveal crop encoded at native detail. |

Foveation works with `encoder_backend = "internvideo_next"` (the default) or `"dinov2"`; it composes with the default InternVideo-Next clip encoder. Enable it only after the host benchmark (`scripts/bench_foveation.py`) confirms two encodes plus native capture fit the tick budget.

## Nous

Section: `[nous]`.

Nous is the active inference engine. It maintains a discrete generative model and selects policies through expected free energy minimization. See [The Nous module](../09-modules/nous.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"pymdp"` | `"pymdp"` runs `inferactively-pymdp` 1.0 on JAX and needs the `[reasoning]` extra. `"numpy"` needs no extra. |
| `factors` | integer | `4` | Declared number of latent state factors; used only for the boot-time complexity-envelope check. |
| `max_states_per_factor` | integer | `4` | Maximum states per factor. |
| `actions` | integer | `4` | Declared action-space size; used only for the complexity-envelope check. |
| `planning_horizon` | integer | `1` | EFE planning horizon (steps). Higher values increase planning cost. |
| `efe_timeout_ms` | float | `250` | Hard timeout for one EFE planning pass. On overrun Nous returns the last posterior and publishes `nous.timeout`. |
| `baseline_salience` | float | `0.4` | Salience of routine belief-update publications. |
| `alert_salience` | float | `0.8` | Salience when EFE selects a non-trivial policy or a timeout occurs. |
| `timeout_salience` | float | `0.3` | Salience of the `nous.timeout` event emitted on an EFE overrun. |
| `drive_actions` | boolean | `true` | When `true`, Nous's chosen actions become proposals that Volition may realize. When `false`, proposals are learned as `no_op`. |

The `factors`, `max_states_per_factor`, `actions`, and `planning_horizon` values are used only for the boot-time complexity-envelope check. The generative model dimensions are fixed by the action-space and factor lists in the code, not by these config keys. The shipped default envelope is 64, well below the 4096 threshold. Exceeding the threshold raises `ConfigurationError`.

### Optional transition priors

These keys are commented out in the shipped file but accepted by `make_nous`.

| Key | Type | Default | Description |
|---|---|---|---|
| `transition_persistence` | float | `0.8` | Dirichlet prior weight for the self-transition of each perceptual factor under every action. |
| `transition_concentration` | float | `1.0` | Total prior concentration for each perceptual-factor transition. |
| `transition_max_concentration` | float | `1000.0` | Upper bound on the total Dirichlet concentration any learned transition column can hold. Must be greater than `transition_concentration`. |

## Embedding

Section: `[embedding]`.

One shared text embedder for Mnemos, Empatheia, Hypnos, and the evaluation sidecar. It is loaded once and configured here.

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"numpy"` | `"numpy"` runs the model in NumPy with no torch. `"sentence_transformers"` uses the torch backend. Both produce the same vectors to within `1e-5`. |
| `model_id` | string | `"sentence-transformers/all-MiniLM-L6-v2"` | HuggingFace model ID. The NumPy backend reads `model.safetensors`, `config.json`, and `vocab.txt`. |
| `device` | string | `"cpu"` | Compute device, read only by the `sentence_transformers` backend. |
| `model_path` | string | *(unset)* | If set, the NumPy backend reads model files from this local directory instead of the HuggingFace cache. The `sentence_transformers` backend ignores it. |

## Mnemos

Section: `[mnemos]`.

Mnemos is the vector-store memory module. It backs episodic, semantic, and procedural collections in Qdrant and uses the shared embedder from `[embedding]`. See [The Mnemos module](../09-modules/mnemos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"qdrant"` | Storage backend: `"qdrant"`, `"inmemory"` for tests or minimal deployments, or `"sqlite_vec"` for Tier 0/1 deployments. |
| `collection_prefix` | string | `"mnemos_"` | Prefix applied to all Qdrant collection names. |
| `short_term_capacity` | integer | `128` | Maximum traces held in the in-process short-term buffer before flushing. |
| `recall_top_k` | integer | `5` | Number of nearest-neighbor results returned per recall query. |
| `recall_on_workspace` | boolean | `true` | Whether Mnemos recalls in response to workspace broadcasts. |
| `recall_cooldown_s` | float | `5.0` | Minimum seconds between recall attempts. |
| `baseline_salience` | float | `0.15` | Salience of routine recall events. |
| `alert_salience` | float | `0.6` | Salience when a high-affect memory surfaces. |

### Qdrant connection

Section: `[mnemos.qdrant]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Qdrant hostname. |
| `port` | integer | `6533` | Qdrant port (KAINE-owned container; not the default 6333/6334). |

The Qdrant API key belongs in `config/secrets.toml`, not in this table.

### Replay

Section: `[mnemos.replay]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `selection_top_k` | integer | `5` | Traces re-injected per Hypnos maintenance window. |
| `affect_weight` | float | `0.7` | Weight on affect intensity in the replay selection score. |
| `recency_weight` | float | `0.3` | Weight on recency in the replay selection score. |
| `redact_content` | boolean | `true` | When `true`, sidecar/observer payloads carry only memory IDs, not trace text. |

## Eidolon

Section: `[eidolon]`.

Eidolon is the self-model: a persisted JSON document of values, behavioral norms, personality baseline, capability map, identity history, and name. A KL-divergence drift detector flags identity shifts. See [The Eidolon module](../09-modules/eidolon.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `persistence_path` | string | `"state/eidolon/self_model.json"` | Path where the self-model is persisted. Encrypted at rest when state encryption is enabled. |
| `drift_window` | integer | `100` | Rolling-window length (observations) for the KL-divergence drift detector. |
| `drift_threshold` | float | `0.6` | KL divergence above which identity drift is flagged as a workspace event. |
| `save_interval_s` | float | `30.0` | Seconds between self-model writes to disk. |
| `internal_speech_stream` | string | `"lingua.internal"` | Bus stream observed for internal speech. |
| `external_speech_stream` | string | `"lingua.external"` | Bus stream observed for external speech output. |
| `identity_history_cap` | integer | `0` | Maximum drift episodes kept in `identity_history`. `0` keeps every episode; negative values are rejected. |
| `voice_observations_cap` | integer | `0` | Maximum speech observations kept in `voice_observations`. `0` keeps every observation; negative values are rejected. |
| `baseline_salience` | float | `0.05` | Salience of routine self-model update events. |
| `alert_salience` | float | `0.7` | Salience on drift detection. |

### Self inference

Section: `[eidolon.self_inference]`.

Observation-driven self-model population. Ships disabled.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. The operator must set `true` to activate it. |
| `vad_window_cycles` | integer | `10` | Number of Hypnos maintenance cycles for rolling VAD mean/variance used in `personality_baseline`. |
| `speech_pattern_min_count` | integer | `5` | Minimum occurrences of a speech-type label before it becomes a `behavioral_norms` entry. |
| `seed_path` | string | *(unset)* | Optional path to an operator-seed JSONL applied once on first boot. |

Privacy note: internal-speech text is never written to disk; only counts and derived numeric or categorical summaries are persisted.

## Thymos

Section: `[thymos]`.

Thymos maintains a dimensional VAD (valence/arousal/dominance) state, categorical emotion, and four drives. See [The Thymos module](../09-modules/thymos.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `baseline_valence` | float | `0.0` | Resting valence. |
| `baseline_arousal` | float | `0.3` | Resting arousal. |
| `baseline_dominance` | float | `0.0` | Resting dominance. |
| `drift_rate_per_s` | float | `0.05` | Rate at which the dimensional state drifts back toward baseline per second. |
| `publish_interval_s` | float | `1.0` | Seconds between affect-state publications to the bus. |
| `baseline_salience` | float | `0.1` | Salience of routine affective state publications. |
| `alert_salience` | float | `0.7` | Salience on significant affective change or drive threshold crossing. |
| `social_drive_time_scale_s` | float | `600.0` | Time scale over which the social drive builds. |
| `soma_stream` | string | `"soma.out"` | Stream observed for interoceptive prediction errors. |
| `chronos_stream` | string | `"chronos.out"` | Stream observed for temporal events. |
| `mnemos_stream` | string | `"mnemos.out"` | Stream observed for memory recall events that trigger affect. |

### Affect coupling

Section: `[thymos.coupling]`.

When enabled, perceived speaker emotion is folded into Thymos's own Scherer appraisal as a transient, familiarity-weighted, decaying input. It is never written directly to the VAD state. Ships disabled.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Also requires Empatheia to provide familiarity scores. |
| `coupling_base` | float | `0.05` | Appraisal-influence weight when no familiarity is known. |
| `coupling_familiarity_gain` | float | `0.10` | Additional appraisal-influence weight per unit of Empatheia familiarity `[0, 1]`. |
| `coupling_ceiling` | float | `0.15` | Hard ceiling on the appraisal-influence weight. |
| `decay_s` | float | `10.0` | Window over which a perceived-emotion signal decays to zero. |

The legacy key `coupling_max_rate_per_s` is ignored if present.

### Drives

Section: `[thymos.drives.<name>]`.

The four shipped drives are `curiosity`, `boredom`, `social_drive`, and `restlessness`.

| Key | Type | Description |
|---|---|---|
| `build_rate` | float | Rate at which the drive accumulates per second under activating conditions; `build_rate` is scaled by the incoming signal. |
| `decay_rate` | float | Rate at which the drive decays per second when conditions are absent. |
| `threshold` | float | Drive level at which a threshold-crossing event is published. |

Shipped defaults:

| Drive | `build_rate` | `decay_rate` | `threshold` |
|---|---|---|---|
| `curiosity` | `0.05` | `0.02` | `0.7` |
| `boredom` | `0.04` | `0.02` | `0.7` |
| `social_drive` | `0.01` | `0.005` | `0.7` |
| `restlessness` | `0.03` | `0.02` | `0.7` |

## Praxis

Section: `[praxis]`.

Praxis exposes bounded effectors: sandboxed file writes, desktop notifications, and shell commands. See [The Praxis module](../09-modules/praxis.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `sandbox_path` | string | `"state/praxis/files"` | Root path for sandboxed file operations. |
| `audit_log_path` | string | `"state/praxis/audit.log"` | Path for the Praxis audit log. Every invocation is logged here. |
| `notification_command` | string | `"notify-send"` | System command used for desktop notifications. |
| `notification_fallback_log` | string | `"state/praxis/notifications.log"` | Fallback log when the notification command fails. |
| `max_file_bytes` | integer | `1048576` | Maximum file size in bytes for sandbox writes (1 MiB). |
| `enabled_effectors` | list of strings | `[]` | First-layer effector whitelist. Only listed effectors are allowed; every other proposed action is blocked before it runs. |
| `baseline_salience` | float | `0.3` | Salience of routine effector events. |
| `alert_salience` | float | `0.7` | Salience on effector errors or denied actions. |

The `enabled_effectors` list is empty by default. The operator opts in explicitly, for example `enabled_effectors = ["file_write", "notify"]`.

### Shell whitelist

Section: `[praxis.shell_whitelist]`.

Empty by default. Each sub-table enables one shell command.

```toml
[praxis.shell_whitelist.echo]
arg_patterns = ["[A-Za-z0-9]+"]
timeout_s = 2.0
description = "echo a single token"
```

| Sub-key | Type | Default | Description |
|---|---|---|---|
| `arg_patterns` | list of strings | — | Regular expressions that each argument must fully match. |
| `timeout_s` | float | `5.0` | Maximum wall-clock time for the command. |
| `cwd` | string | *(unset)* | Working directory for the command. Omit to use the KAINE working directory. |
| `description` | string | *(unset)* | Human-readable label for audit logs. |

## Lingua

Section: `[lingua]`.

Lingua is the language organ. It calls a local OpenAI-compatible model server at `/v1/chat/completions` and uses a local abliterated model so the cognitive stack governs behavior rather than baked-in refusals. See [The Lingua module](../09-modules/lingua.md) and [Verification](../18-verification.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `chat_url` | string | `"http://127.0.0.1:11434/v1"` | Base URL of the model server. The client posts to `/v1/chat/completions`. |
| `model_id` | string | `"kaineone/Qwen3.5-4B-abliterated-GGUF"` | Served alias of the published KAINE organ. It must match a model the server serves. |
| `temperature` | float | `0.7` | Sampling temperature for generation. |
| `max_tokens` | integer | `512` | Maximum tokens per generation. |
| `request_timeout_s` | float | `60.0` | HTTP request timeout for model server calls. |
| `model_server_sleep_idle_seconds` | integer | `600` | Seconds of inactivity before the natively launched organ server unloads the model; `-1` keeps it loaded. |
| `intent_log_path` | string | `"state/lingua/intent_expression.jsonl"` | Path where intent/expression preference pairs are logged for Hypnos voice alignment. |
| `baseline_salience` | float | `0.4` | Salience of routine expression events. |
| `alert_salience` | float | `0.7` | Salience on generation errors or high-divergence outputs. |

`model_server_sleep_idle_seconds` is read when KAINE launches the organ natively. Container and Quadlet deployments read `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` instead.

### Secrets and local loader keys

| Key | Type | Default | Description |
|---|---|---|---|
| `api_key` | string | *(unset)* | Bearer token for a keyed server. Prefer the `KAINE_MODEL_SERVER_API_KEY` environment variable so the secret never lands in a file. |
| `backend` | string | *(unset)* | Model backend selector: `"openai"` (or its alias `"ollama"`) for an OpenAI-compatible HTTP server, `"llama_cpp"` for in-process GGUF loading. |
| `gguf_path` | string | *(unset)* | Local path to a GGUF file. |
| `gguf_filename` | string | *(unset)* | Filename within `gguf_path`. |

### Additional generation keys

| Key | Type | Description |
|---|---|---|
| `think` | boolean | Default: `false`. `false` sends `chat_template_kwargs: {"enable_thinking": false}` to suppress chain-of-thought; `true` allows chain-of-thought. Only a Python `None` value omits the key entirely, and TOML cannot express that. |
| `context_max_events` | integer | Maximum workspace broadcast events included in the assembled context. Default: `8`. |
| `context_char_budget` | integer | Character budget for the context block. Default: `2000`. |
| `persona_name` | string | Entity's persona name, seeded from Eidolon at runtime. |
| `persona_external` | string | External persona prompt fragment. |
| `persona_internal` | string | Internal persona prompt fragment. |

Inspect served models with:

```bash
curl -s http://127.0.0.1:11434/v1/models
```

## Audition

Section: `[audition]`.

Audition is the hearing module: live microphone capture, optional speech-to-text, vocal-emotion classification, and general acoustic perception. Raw audio stays in memory and is never written to disk. See [The Audition module](../09-modules/audition.md) and [Perception feed and sleep](perception-and-sleep.md) for the deterministic A/V feed.

| Key | Type | Default | Description |
|---|---|---|---|
| `speaches_url` | string | `"http://127.0.0.1:8000"` | URL of the Speaches STT service. |
| `backend` | string | `"speaches"` | STT backend: `"speaches"` or `"sherpa_onnx"`. |
| `sherpa_model_id` | string | `"moonshine-base-en"` | sherpa-onnx STT model ID. |
| `sherpa_model_dir` | string | *(unset)* | Directory holding the downloaded sherpa-onnx model files. Default: `<models dir>/sherpa-onnx/<id>`. |
| `sherpa_num_threads` | integer | `2` | ONNX Runtime threads for sherpa-onnx. |
| `transcription_enabled` | boolean | `false` | Master gate on the STT path. Speech-to-text is built but deactivated by default in the shipped config. |
| `general_audition` | boolean | `false` | Master gate on general acoustic (non-speech) perception. The `thesis_test` profile enables this. |
| `stt_model` | string | `"Systran/faster-distil-whisper-medium.en"` | STT model ID that Speaches has loaded. Must match a served model. |
| `emotion_model_id` | string | `"emotion2vec/emotion2vec_plus_base"` | HuggingFace hub ID for the emotion2vec+ vocal emotion model. |
| `emotion_device` | string | `"cpu"` | Compute device for emotion2vec+. |
| `request_timeout_s` | float | `60.0` | HTTP timeout for Speaches requests. |
| `baseline_salience` | float | `0.4` | Salience of routine transcription events. |
| `alert_salience` | float | `0.8` | Salience on speech detection or high-affect emotional content. |

For sherpa-onnx install the `speech-edge` extra and fetch models with `python -m kaine.setup.speech_models --stt moonshine-base-en`.

### General auditory perception

| Key | Type | Default | Description |
|---|---|---|---|
| `arousal_window_min` | float | `0.15` | Lower bound of the arousal-modulated acoustic analysis window in seconds. |
| `arousal_window_max` | float | `1.0` | Upper bound of the arousal-modulated acoustic analysis window in seconds. |
| `acoustic_change_alert_threshold` | float | `0.35` | Small absolute floor guard on the acoustic change alert. |
| `acoustic_change_alert_factor` | float | `2.0` | Relative multiplier: an acoustic onset alerts when it reaches this factor times the rolling-window mean of change scores. |
| `acoustic_encoder` | string | `"spectral"` | Acoustic encoder for general auditory perception: `"spectral"`, `"dasheng"` or `"wavjepa"`. An unknown name fails at boot. The self-supervised encoders need their weights fetched once at setup. A plugin may supply the encoder through the `audition.acoustic_encoder` seam instead. |
| `acoustic_device` | string | `"cpu"` | Device for the self-supervised acoustic encoders, resolved like other module devices. |

The forward-model prediction-error path is always active and is the primary driver of auditory salience.

### Live microphone

| Key | Type | Default | Description |
|---|---|---|---|
| `capture_enabled` | boolean | `false` | Enable live microphone capture. Requires the `[audio]` extra. |
| `capture_device` | string | `""` | Input device name. Empty selects the OS default input device. |
| `capture_sample_rate` | integer | `16000` | Sample rate in Hz. Whisper expects 16 kHz. |
| `capture_channels` | integer | `1` | Number of audio channels. |
| `vad_backend` | string | `"webrtcvad"` | Voice-activity backend: `"webrtcvad"` or `"rms"`. |
| `vad_aggressiveness` | integer | `2` | webrtcvad aggressiveness: `0` to `3`. |
| `vad_frame_ms` | integer | `30` | Frame duration for webrtcvad: `10`, `20`, or `30`. |
| `min_utterance_ms` | integer | `300` | Minimum utterance duration; shorter events are discarded. |
| `max_utterance_ms` | integer | `30000` | Maximum utterance duration; longer speech is split. |
| `silence_hangover_ms` | integer | `600` | Post-speech silence before the utterance is closed. |
| `desired_state_poll_ms` | integer | `250` | Poll interval for checking the perception desired-state. |

### Forward model and prosody

| Key | Type | Default | Description |
|---|---|---|---|
| `forward_model_units` | integer | `32` | Hidden units of the auditory forward model. |
| `prediction_error_window` | integer | `32` | Rolling-window size (utterances) for normalizing the prediction error signal. |
| `auditory_buffer_size` | integer | `16` | Number of recent utterance feature vectors kept in the recurrent buffer. |
| `prosody_enabled` | boolean | `false` | Enable in-memory speaker prosody extraction with librosa. Required by `[vox.mirroring]`. Publishes numeric features only. |

## Vox

Section: `[vox]`.

Vox is the voice synthesis module. It calls Chatterbox or sherpa-onnx (Kokoro) and modulates prosody with Thymos affect. See [The Vox module](../09-modules/vox.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `chatterbox_url` | string | `"http://127.0.0.1:8883"` | URL of the Chatterbox TTS server. |
| `backend` | string | `"chatterbox"` | Synthesis backend: `"chatterbox"` or `"sherpa_onnx"`. |
| `sherpa_model_id` | string | `"kokoro-en"` | sherpa-onnx TTS model ID. |
| `sherpa_speaker_id` | integer | `0` | Kokoro speaker index. |
| `sherpa_model_dir` | string | *(unset)* | Directory holding the downloaded sherpa-onnx model files. |
| `sherpa_num_threads` | integer | `2` | ONNX Runtime threads for sherpa-onnx. |
| `voice_mode` | string | `"predefined"` | Voice mode. Only `"predefined"` is currently used with Chatterbox. |
| `predefined_voice_id` | string | *(unset)* | Required when `voice_mode = "predefined"`. Filename of a voice served by Chatterbox. |
| `output_format` | string | `"wav"` | TTS output format passed to Chatterbox. |
| `sink_path` | string | `"state/vox"` | Directory where synthesized audio files are written when sinking is enabled. |
| `baseline_temperature` | float | `0.7` | Default sampling temperature. |
| `baseline_exaggeration` | float | `0.5` | Default prosodic exaggeration. |
| `baseline_cfg_weight` | float | `0.5` | Default classifier-free guidance weight. |
| `request_timeout_s` | float | `120.0` | HTTP timeout for Chatterbox requests. |
| `baseline_salience` | float | `0.3` | Salience of routine speech-synthesis events. |
| `alert_salience` | float | `0.7` | Salience on synthesis errors. |
| `lingua_external_stream` | string | `"lingua.external"` | Stream observed for external speech text. |
| `thymos_state_stream` | string | `"thymos.out"` | Stream observed for affect-state updates. |

List Chatterbox voices with:

```bash
curl -s http://127.0.0.1:8883/get_predefined_voices
```

Vox cannot speak until `predefined_voice_id` is set.

### Additional playback and sink keys

| Key | Type | Description |
|---|---|---|
| `playback_enabled` | boolean | Enable real-time audio playback. Default: `true`. |
| `output_device` | string | Output audio device name. Default: `""` (OS default). |
| `sink_enabled` | boolean | Enable writing synthesized files to `sink_path`. Default: `false`. |
| `retain_count` | integer | Number of recent audio files to retain in `sink_path`. Default: `0`. |
| `suppress_self_hearing` | boolean | Gate Audition's microphone during Vox output. Default: `true`. |
| `mic_mute_hangover_ms` | integer | Extra silence to keep the microphone muted after speech ends. Default: `600`. |

### Prosodic mirroring

Section: `[vox.mirroring]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. Also requires `[audition].prosody_enabled = true`. |
| `mirror_strength` | float | `0.3` | Blending coefficient, clamped to `mirror_ceiling`. |
| `mirror_ceiling` | float | `0.5` | Hard ceiling on the mirror influence. |
| `decay_s` | float | `10.0` | Seconds after the last `audition.prosody` event before the mirror residual decays to zero. |

## Empatheia

Section: `[empatheia]`.

Empatheia is the social-cognition / theory-of-mind module. It builds agent models and drives the familiarity coefficient in `[thymos.coupling]`. Ships disabled. See [The Empatheia module](../09-modules/empatheia.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"qdrant"` | Storage backend: `"qdrant"` or `"inmemory"`. |
| `collection` | string | `"empatheia_agents"` | Qdrant collection name for agent profiles. |
| `speaker_label` | string | `"operator"` | Default speaker label for the single-partner v1 mode. |
| `operator_sources` | list of strings | `["live_mic", "microphone", "remote"]` *(commented)* | Audio channels attributed to the operator. Other channels are modelled as `media:<channel>`. |
| `deviation_threshold` | float | `0.5` | Deviation above this triggers `empatheia.social_error`. |
| `baseline_salience` | float | `0.15` | Salience of routine agent-model updates. |
| `alert_salience` | float | `0.6` | Salience on social prediction errors. |

### Qdrant connection

Section: `[empatheia.qdrant]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Qdrant hostname (same container as Mnemos). |
| `port` | integer | `6533` | Qdrant port. |

## Phantasia

Section: `[phantasia]`.

Phantasia is the world-model / imagination module. It uses a DreamerV3-style RSSM core with no actor or critic; action selection stays in Nous. See [The Phantasia module](../09-modules/phantasia.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"dreamerv3"` | World-model backend: `"dreamerv3"` (real RSSM) or `"fake"` (dev-only non-learning EMA stub). |
| `engine` | string | `"jax"` | Compute engine for `"dreamerv3"`: `"jax"` (requires the `[worldmodel]` extra) or `"numpy"` (no extra). |
| `training_enabled` | boolean | `true` | Enable sleep-time in-memory world-model training. Training writes no trajectory data to disk. |
| `training_device` | string | `"cpu"` | JAX compute device for training. GPU is opt-in. |
| `trajectory_buffer_size` | integer | `512` | Bounded in-memory waking-trajectory ring buffer size. |
| `rollout_horizon` | integer | `8` | Imagined-trajectory length for offline scenario generation. |
| `persist_weights` | boolean | `true` | Persist learned world-model weights across restarts. Requires `backend = "dreamerv3"`; pairing it with `"fake"` is a configuration error. |
| `checkpoint_path` | string | `"state/phantasia/world_model.ckpt"` | Where the weight checkpoint lives. |
| `mnemos_stream` | string | `"mnemos.out"` | Stream observed for memory recall events. |
| `hypnos_stream` | string | `"hypnos.out"` | Stream observed for Hypnos maintenance events. |

Weights are saved atomically after each successful sleep-training pass and on graceful shutdown, loaded at boot, and encrypted at rest when state encryption is enabled. An incompatible checkpoint fails the boot closed.

### Salience

Section: `[phantasia.salience]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `baseline` | float | `0.1` | Salience of routine world-model prediction publications. |
| `alert` | float | `0.7` | Salience on high world-model prediction error. |

### World model hyperparameters

Section: `[phantasia.world_model]`. Ignored by the `"fake"` backend.

| Key | Type | Default | Description |
|---|---|---|---|
| `deter_dim` | integer | `64` | Deterministic recurrent state dimensionality (GRU hidden size). |
| `stoch_dim` | integer | `16` | Stochastic latent dimensionality. |
| `stoch_classes` | integer | `8` | Number of classes for categorical stochastic latent. Ignored when `latent_kind = "gaussian"`. |
| `hidden_dim` | integer | `64` | Hidden-layer width of the encoder and decoder MLPs. |
| `latent_kind` | string | `"categorical"` | Stochastic latent distribution: `"categorical"` or `"gaussian"`. |
| `learning_rate` | float | `0.001` | Adam learning rate for world-model training. |

## Mundus

Section: `[mundus]`.

Mundus is the body-agnostic embodiment control plane. It routes perception and action to a body through a pluggable adapter. The shipped default is the local `stub` reference body. See [The Mundus module](../09-modules/mundus.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Config-layer gate. |
| `adapter` | string | `"stub"` | Adapter to construct. Only this adapter's `[mundus.<adapter>]` table is read. |
| `mirror_speech` | boolean | `true` | Forward Lingua external speech to the body as local-chat `say` actions. |
| `speech_stream` | string | `"lingua.external"` | Stream observed for speech to mirror. |

Three gates must all be true before any action reaches a body: the module toggle `[modules].mundus = true`, the config flag `[mundus].enabled = true`, and the environment variable `KAINE_MUNDUS_OPERATOR_APPROVED=1`.

Exposure flags are read from the selected adapter's `[mundus.<adapter>]` table as `expose_<name>` booleans. A name the body declares as a continuous channel sets that channel's exposure; a name it declares as an action family sets that family's exposure; any other name refuses boot. With the `stub` body, for example, `expose_drive = true` exposes the `drive` channel.

### Control surface

Section: `[mundus.control_surface]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Construct the per-tick continuous motor producer. The surface is built but inert at runtime; nothing drives its per-tick loop yet. |
| `competence_threshold` | float | `0.05` | A degree of freedom is freed only when the rolling forward-model prediction error is at or below this. |
| `min_samples` | integer | `32` | Minimum observed ticks before competence is judged. |
| `window` | integer | `64` | Rolling window of prediction errors for the competence readout. Must be ≥ `min_samples`. |

## Perception locus

Section: `[perception]`.

The perception locus arbiter gates physical versus virtual senses. Enabled via `[modules].perception = true`. When the entity is embodied in a virtual world its physical camera and microphone are inhibited, and vice-versa.

| Key | Type | Default | Description |
|---|---|---|---|
| `allow_self_switch` | boolean | `false` | Allow the entity to switch its own perceptual locus via Praxis intents. Reserved for deferred virtual-world embodiment work; no module currently produces `intent.perception.switch`, so this flag has no effect. |
| `min_dwell_s` | float | `30.0` | Minimum seconds the locus must hold before another switch is honoured. |
