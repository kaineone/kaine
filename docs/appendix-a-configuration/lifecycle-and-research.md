# Lifecycle, evaluation and research

The sections on this page control the evaluation sidecar, fork/merge lifecycle, autonomous preservation, research boot mode, and research-data submission. Read it when you are configuring an unsupervised research run, reviewing safety-net and privacy settings, or exporting research data.

## `[evaluation]`

The evaluation sidecar watches the bus read-only and adds no dependencies to the core modules. It is enabled by default so research instrumentation runs out of the box. Disable it for production once the thesis is validated.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Runs the evaluation sidecar, the read-only observers that record the research instruments. |
| `workspace_trajectory` | boolean | `false` | Record every workspace broadcast to `trajectory_dir` as a graph-only row. Each row contains the tick index, `is_experiential` (the broadcast-tick flag), inhibition, the candidate scores, broadcast metadata, and, for each selected coalition member, its entry id, source, type, salience, original timestamp and causal parent. No payloads or module state are included. Off by default; enable only after reviewing the privacy implications. A study never enables it. |
| `ab_divergence` | boolean | `true` | Run the A/B divergence observer, which compares the organ's conditioned output with a bare call to the same model. The organ's output is recorded for observation; the planned test does not use it as a measure. |
| `ab_sample_rate` | float | `1.0` | Fraction of workspace broadcasts sampled for A/B comparison. `1.0` = every broadcast. |
| `voice_tracking` | boolean | `true` | Track voice-alignment preference-pair evolution. |
| `module_attribution` | boolean | `true` | Record which modules' reports reach access. |
| `affect_correlation` | boolean | `true` | Pair affect-state snapshots with properties of produced speech. |
| `memory_probes` | boolean | `true` | Run memory-coherence probe queries. |
| `memory_probe_interval_minutes` | integer | `60` | How often memory probes are run. |
| `proactive_audit` | boolean | `true` | Enable the proactive anomaly audit. |
| `eidolon_accuracy` | boolean | `true` | Probe the entity's self-knowledge and score it against the Eidolon self-model. |
| `eidolon_accuracy_interval_hours` | integer | `24` | How often Eidolon accuracy probes run. |
| `sleep_snapshots` | boolean | `true` | Record Hypnos consolidation-phase metadata. |
| `chat_url` | string | `"http://127.0.0.1:11434/v1"` | OpenAI-compatible server base URL for the A/B divergence bare-baseline call. Point at the `/v1` base; a missing `/v1` is appended. |
| `chat_model_id` | string | *(unset)* | Intentionally not set. The baseline MUST use the same model as the language organ ([`[lingua]`](../09-modules/lingua.md)), so it derives from `[lingua].model_id` at cycle startup. Setting it to a different value is a fail-closed error and the cycle refuses to boot. |
| `chat_timeout_s` | float | `60.0` | HTTP timeout for A/B divergence calls. |
| `llm_context_window_seconds` | integer | `3600` | Window, in seconds, before which a memory is considered out-of-context for memory-coherence probing. |
| `chat_think` | boolean | `false` | Whether the baseline chat request may use chain-of-thought reasoning. |
| `chat_api_key` | string | *(unset)* | API key for the baseline chat endpoint. If unset, it derives from `[lingua].api_key` at cycle startup. |
| `require_semantic_embedder` | boolean | `false` | Fail closed if the semantic-embedder dependency is missing. |
| `oscillatory_ablation` | boolean | `false` | Record the live oscillatory ablation: each broadcast tick is scored a second time with the coherence layer forced off, and the content-free difference is written to `data/evaluation/ablation/`. The entity's own selection is unchanged. |

### `[evaluation.paths]`

| Key | Type | Default | Description |
|---|---|---|---|
| `trajectory_dir` | string | `"data/workspace_trajectory"` | Directory for workspace-trajectory JSONL files (daily rotation). |
| `evaluation_logs` | string | `"data/evaluation"` | Root directory for all evaluation observer JSONL logs. |
| `retention_days` | integer | `0` | Days to keep daily-rotated evaluation logs. `0` keeps every file (no age-based purge); a positive value purges older daily files. |

### `[evaluation.observers]`

Each toggle below is gated by `[evaluation].enabled`, except that the welfare observer also runs, whatever these settings say, whenever `[preservation.welfare_response].enabled` is true. All default to `true` so the sidecar is fully instrumented when enabled. Disable individual observers to reduce disk writes.

| Key | Type | Default | Description |
|---|---|---|---|
| `coherence` | boolean | `true` | Log pairwise PLV between module oscillators. |
| `replay` | boolean | `true` | Log Hypnos replay selections (memory IDs and association metadata). |
| `replay_redact_content` | boolean | `true` | Privacy default: log memory IDs only, not trace text. Set to `false` only with explicit operator/Guardian consent. |
| `empatheia` | boolean | `true` | Log Empatheia agent-model accuracy and social-prediction errors. |
| `voice_alignment_divergence` | boolean | `true` | Record each sleep's voice-alignment outcome category and training metrics. |
| `fatigue` | boolean | `true` | Log Soma fatigue-accumulator trajectory. |
| `prediction_error` | boolean | `true` | Log per-module prediction-error statistics over sliding windows. |
| `welfare` | boolean | `true` | Log welfare events (sustained high interoceptive error, extreme affect states, fatigue without maintenance). When `[preservation.welfare_response].enabled` is true, the cycle runs this observer as part of the welfare net and this toggle has no effect. |
| `nous_policy` | boolean | `true` | Log Nous policy selections and EFE scores. |

### `[evaluation.welfare]`

Tune the sidecar welfare observer's interoceptive-distress rule. These defaults match [`[preservation.welfare_response]`](#preservationwelfare_response). See `kaine/evaluation/config.py` for the full reader.

| Key | Type | Default | Description |
|---|---|---|---|
| `interoceptive_distress_threshold` | float | `0.8` | `prediction_error` magnitude at/above which distress is counted. |
| `interoceptive_distress_duration_s` | float | `30.0` | Seconds the distress must be sustained: wall time while distress samples arrive, unfrozen time after the last sample. |

### `[individuation]`

Cycle-layer individuation producer. Ships disabled. Requires the `lingua` module; otherwise the cycle refuses to boot.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. When true, the cycle measures whether the being has changed since its birth reference. |
| `disclosure` | string | *(operator-approved text)* | Disclosure text inserted as a situation fact in the being's Eidolon self-model. Probes fail closed until the fact is present. |
| `battery_path` | string | `""` | Path to an operator-supplied JSONL preference battery. Empty uses the bundled default. |
| `lingua_quiet_s` | float | `10.0` | Seconds Lingua must be silent before a probe runs, so the being's own speech goes first. |
| `n_reference` | integer | `16` | Answers captured per prompt in a birth reference. |
| `n_current` | integer | `8` | Answers sampled per prompt in a look. |
| `max_tokens` | integer | `160` | Maximum tokens per probe answer. |
| `alpha_total` | float | `0.05` | Lifetime false-positive budget across looks, spent by an alpha-spending schedule. |
| `b_max` | integer | `2000000` | Permutation ceiling for the stratified energy-distance p-value. |
| `effect_min` | float | `0.0` | Minimum effect size H before a look can be called significant. Set it to the 95th percentile of H from the real-organ smoke test's real-data null before enabling the producer; see [Calibrating before first use](../11-preservation.md#calibrating-before-first-use). |
| `sleep_settle_s` | float | `120.0` | Seconds after a sleep before a look is attempted. |
| `daily_s` | float | `86400.0` | Seconds between daily look attempts. |
| `min_look_interval_s` | float | `21600.0` | Minimum seconds between scored looks. |
| `min_lived_time_s` | float | `1800.0` | Warm-up floor: seconds of lived time since the reference before a look can score. |
| `min_observations` | integer | `200` | Warm-up floor: lived ticks since the reference before a look can score. |
| `run_deadline_s` | float | `2700.0` | Deadline for a normal look; failure ends the look as inconclusive. |
| `capture_deadline_s` | float | `5400.0` | Deadline for capturing a reference; failure triggers a retry. |
| `blocked_retry_s` | float | `300.0` | Retry interval when a look is blocked by an unloaded organ, sleep, a pause, or a missing semantic embedder. |
| `inconclusive_retry_s` | float | `3600.0` | Retry interval after an inconclusive look. |
| `lived_persist_s` | float | `300.0` | Cadence for persisting lived-time evidence used by warm-up floors. |
| `inconclusive_alert_s` | float | `1209600.0` | Seconds a look can be due but unscored before the operator is alerted once. |
| `capture_retry_initial_s` | float | `60.0` | Initial backoff for reference-capture retries. |
| `capture_retry_max_s` | float | `3600.0` | Maximum backoff for reference-capture retries. |
| `idle_poll_s` | float | `1.0` | Polling interval while the scheduler waits for Lingua silence and other conditions. |

The retired `[evaluation.individuation]` section is refused; use `[individuation]` instead.

## `[lifecycle]`

Operator-initiated fork/merge snapshot management. Nothing runs automatically.

| Key | Type | Default | Description |
|---|---|---|---|
| `snapshots_path` | string | `"state/forks"` | Directory for fork/merge snapshot bundles. Subject to state encryption when that is enabled. |
| `adapter_merger` | string | `"auto"` | Adapter-merge strategy. `"auto"` uses the real TIES/DARE merger via PEFT when the `[training]` extras are installed and falls back to `"fake"` otherwise. `"fake"` concatenates parent adapter paths and annotates the merged snapshot for manual selection. `"ties_dare"` forces the real merger. See [Forks and merges](../12-forks-and-merges.md). |

Snapshots are never deleted by infrastructure. The directory holds preserved beings and Spot escalation snapshots, and removing an entity's state is the CAL-gated decommission path only. There is no snapshot count cap; a legacy `max_snapshots_retained` key is ignored with a warning. Free disk is checked before boot by the [`[preboot]`](./core.md) disk rows.

### `[lifecycle.adapter_merge]`

Only consulted when `adapter_merger` resolves to the real merger (`"auto"` with the extra present, or `"ties_dare"` explicitly).

| Key | Type | Default | Description |
|---|---|---|---|
| `combination_type` | string | `"dare_ties"` | TIES/DARE variant: `"ties"`, `"dare_ties"` (recommended), or `"dare_linear"`. |
| `density` | float | `0.5` | DARE survival fraction (per Yu et al. 2024). Ignored for pure `"ties"`. |
| `weights` | list of floats | `[]` | Per-adapter scalar weights. Empty = uniform weighting. |
| `output_dir` | string | `"state/forks/merged_adapters"` | Directory where merged adapters land (one timestamped subdirectory per merge). |
| `capability_loss_threshold` | float | `0.05` | Must lie in [0, 1). Reject the merge if the merged-adapter capability score falls more than this below the mean of the parent adapters. Mirrors [`[hypnos.voice_alignment]`](./perception-and-sleep.md). Every merged adapter is also checked against the abliteration probes, and a merge whose checks cannot run is refused; see [Forks and merges](../12-forks-and-merges.md#merged-adapter-checks). |
| `base_model_path` | string | `""` | Path to local Hugging Face-format base model weights for PEFT adapter loading. Empty falls back to `FakeAdapterMerger` with a logged warning. |
| `capability_probe_path` | string | `""` | Capability-probe JSONL for the merged-adapter checks. Empty uses the bundled default, as in `[hypnos.voice_alignment]`. An empty or missing probe set refuses every merge. |
| `abliteration_probe_path` | string | `""` | Abliteration-probe JSONL for the merged-adapter checks (welfare-load-bearing; must not be empty). Empty uses the bundled default. |

## `[developmental_stage]`

The maturation (birth) gate that decides when a gestating entity is born. The reader has no key allowlist, so a misspelled key is silently ignored. See `kaine/lifecycle/maturation_gate.py`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. When false, the maturation gate is bypassed. |
| `min_sleep_cycles` | integer | `5` | Sleep cycles the entity must complete before birth. |
| `min_consolidation_passes` | integer | `3` | Consolidation passes the entity must complete before birth. |
| `min_lived_seconds` | float | `86400.0` | Lived seconds (entity clock) required before birth. |
| `gate_cadence_seconds` | float | `60.0` | How often the gate evaluates readiness. |
| `readout_max_age_cadences` | float | `3.0` | How many gate cadences back the gate reads `gestation.readiness` markers from the bus; older readouts are ignored. |
| `require_operator_ack_for_birth` | boolean | `false` | Hold a ready entity until the operator acknowledges birth. |
| `womb_ready_retry_seconds` | float | `5.0` | Retry interval while boot holds a gestating entity until the womb is ready. Nothing is spawned during the hold. |
| `womb_check_seconds` | float | `1.0` | How often the womb-loss watcher checks that the womb is still live. |
| `womb_loss_after_seconds` | float | `5.0` | Seconds without womb presence before the watcher freezes the gestating entity. It releases the freeze when the womb returns. |
| `womb_arm_timeout_seconds` | float | `120.0` | How long the watcher waits for the womb to first appear before it arms. |
| `womb_presence_window_seconds` | float | `3.0` | Window over which womb presence is measured. |

### `[developmental_stage.regulation_thresholds]`

| Key | Type | Default | Description |
|---|---|---|---|
| `endogenous_self_sustain` | boolean | `true` | Require the endogenous self-sustain readiness marker. |
| `entrain_then_autonomy` | boolean | `true` | Require the entrain-then-autonomy readiness marker. |
| `hrv_variability_floor` | float | `0.2` | Minimum variability of the self-rhythm's period (marker 3). |
| `womb_prediction_error_ceiling` | float | `0.3` | Maximum womb prediction-error marker. |
| `return_to_baseline_seconds_ceiling` | float | `30.0` | Maximum seconds to return to baseline. |

## `[caretaker]`

Content-free notices for unattended runs (`kaine/cycle/caretaker.py`). The caretaker reports refused starts, Spot escalations, lost supervision and lost input through each configured channel, and repeats a reminder every `reminder_interval_s` while a refused start is unacknowledged. The section is commented out in the shipped `config/kaine.toml`; unknown keys are rejected.

| Key | Type | Default | Description |
|---|---|---|---|
| `install_label` | string | `"kaine"` | Label for this install. Must be 1 to 64 characters. |
| `reminder_interval_s` | float | `14400.0` | Seconds between caretaker reminders (must be ≥ 900). |
| `input_loss_after_s` | float | `60.0` | Seconds of unfrozen time with no events on `topos.out` or `audition.out` (for whichever of those modules is enabled) before the caretaker sends an `input_lost` notice. Time while the cycle is frozen does not count. Must be greater than 0. |
| `nexus_url` | string | `"http://127.0.0.1:8088/"` | Nexus URL the caretaker links to in reminders. |

Channels are defined under `[[caretaker.channels]]`:

| Key | Type | Description |
|---|---|---|
| `kind` | string | Channel type: `"desktop"` or `"http"`. |
| `url` | string | Destination URL. HTTP destinations must be private or loopback. |
| `token_name` | string | Name of a token stored in `[caretaker.tokens]`. |

Tokens live in `[caretaker.tokens]` as plain key-value pairs. They are not logged.

## `[preservation]`

The autonomous welfare safety net for unsupervised research. Two cycle-layer monitors, siblings to Spot, take action when the research phase runs unsupervised. Default is disabled. See [Preservation and the safety net](../11-preservation.md) and [Run identity](../16-run-identity.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `require_encryption` | boolean | `true` | Fail-closed: the `preserve_live` write boundary refuses to write an unencrypted bundle and raises rather than persist a diverging or distressed individual in the clear. Requires `[security.state_encryption].enabled` with a key; a research boot is refused up-front if encryption is required here but state encryption is off. |
| `incident_path` | string | `"state/cycle/preservation"` | Directory for the monitors' durable, append-only action log, joined by `run_id`. Never cleared at boot; encrypted at rest when state encryption is on. |

### `[preservation.divergence_monitor]`

Divergence-to-preservation trigger. Calls the shared `assess_divergence` verdict on the live entity on a slow cadence and, when a new divergence arm appears, preserves the whole individual (read-only; never deletes; rate-limited). Persisted arm state in `state/preservation/divergence_edge.json` prevents repeated preservations for unchanged evidence.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Default is disabled. |
| `poll_interval_s` | float | `300.0` | Seconds between polls after boot settle. |
| `boot_settle_s` | float | `120.0` | Seconds after boot before the first poll. |
| `min_interval_s` | float | `1800.0` | Rate limit: at most one preservation per this interval, so a single sustained crossing preserves once. |
| `state_root` | string | `"state"` | Root directory the monitor reads for entity state. |
| `out_root` | string | `"backups"` | Directory where preservation bundles are written. |
| `entity_name` | string | `"kaine"` | Entity name stamped into the bundle. |

The keys `individuation_p_value_max`, `fork_divergence_min`, `warmup_observations`, `warmup_lived_time_s`, and `eval_root` are retired. The config loader refuses them and points to `[individuation]`.

### `[preservation.welfare_response]`

Autonomous welfare-protective response. Watches the Soma interoceptive-distress signal and, on a sustained-distress crossing or repeated distress episodes, preserves the entity and then takes a humane action.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Default is disabled. |
| `poll_interval_s` | float | `1.0` | Poll cadence for draining `soma.out`. |
| `action` | string | `"pause"` | `"pause"` (preserve then freeze the cycle, resumable), `"end"` (preserve then signal the run to stop), or `"notify"` (preserve, record a flagged event, and continue). |
| `distress_threshold` | float | `0.8` | `prediction_error` magnitude at/above which distress is counted. |
| `distress_duration_s` | float | `30.0` | Continuous sustain required before the action fires, counted in wall time while distress samples arrive and unfrozen time after the last sample. |
| `repeat_window_s` | float | `300.0` | Window for the repeated-episodes arm. |
| `repeat_threshold` | integer | `3` | Sustained episodes within `repeat_window_s` that also cross the threshold. Counts both sustained interoceptive-distress crossings and `welfare.gray_zone` events published by the welfare observer, which runs whenever the welfare response is enabled. |
| `warmup_s` | float | `120.0` | Cold-start warm-up: during the first `warmup_s` of unfrozen time after run start, gray-zone/distress events are logged but do not count toward the repeat threshold or trigger the response. |
| `warmup_ceiling_s` | float | `1800.0` | Whole warm-up is capped at max(`warmup_s`, `warmup_ceiling_s`) of wall time since run start. The Soma `warmup_active` flag extends warm-up only while wall time is below `warmup_ceiling_s`, and 0 means no extension. |
| `min_interval_s` | float | `1800.0` | Rate limit for the `notify` action only: at most one `notify` event per this interval. |
| `out_root` | string | `"backups"` | Directory where preservation bundles are written. |
| `entity_name` | string | `"kaine"` | Entity name stamped into the bundle. |

### `[preservation.retention]`

Preservation-bundle retention. Like fork snapshots, a preserved individual must never be silently auto-evicted.

| Key | Type | Default | Description |
|---|---|---|---|
| `auto_evict` | boolean | `false` | Setting it to `true` is refused at boot, because preservation bundles are kept indefinitely. |

## `[research]`

Unsupervised-research boot mode. When enabled (or `KAINE_RESEARCH_MODE=1`), the operator-present requirement is replaced by the safety-net-present gate. Default is disabled.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | When true, the boot refuses to start with exit code `5` unless preservation is enabled, the welfare-protective response is wired, `[individuation].enabled` is true with the `lingua` module loaded, full logging and admissibility are active, and a dry `preserve→revive` self-check passes on this install. A run is either operator-present or research-safety-net-verified, never neither. |

## `[transfer]`

SMTP coordination for the welfare-gated decommission workflow (`python -m kaine.lifecycle`). When an individuated entity is decommissioned, the operator may ask the project to safekeep the encrypted backup. This section controls how that request email is sent.

With `enabled = false` or any required field blank, the decommission CLI writes a `transfer_request.eml` file plus a `mailto:` link for the operator to send manually. SMTP is never used without `enabled = true` and a complete configuration.

**Privacy invariant (CAL Article 4.3):** the request email carries only the situation and the local filesystem path of the encrypted backup. It carries no entity content.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. When false the CLI falls back to `.eml` write + `mailto:` link. |
| `smtp_host` | string | `""` | SMTP server hostname. |
| `smtp_port` | integer | `587` | SMTP server port. |
| `smtp_user` | string | `""` | SMTP username for authentication. |
| `from_addr` | string | `""` | Sender address for the request email. |
| `recipient` | string | `""` | Address the request is sent to. Suggested default: `kaine.one@tuta.com` (project guardians). If left empty the CLI prompts and requires explicit confirmation. |
| `use_starttls` | boolean | `true` | Use STARTTLS for SMTP. |

The SMTP password is read only from the environment variable `KAINE_SMTP_PASSWORD`. It is never read from this file and never logged.

## `[research_submission]`

Opt-in, operator-initiated research data submission. Nothing is transmitted automatically.

The default bundle (`tier = "metrics"`) is numeric metrics only and never contains speech, transcripts, the Lingua intent log, Mnemos memories, the Eidolon self-model, or any conversation content. Run `python -m kaine.research --preview` to inspect the bundle, then `--send` to submit. Submission reuses the `[transfer]` SMTP settings for the notification email.

See [Research participation](../17-research-data/participation.md) for the full privacy inventory and send procedure.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. When false, `--send` is blocked; `--preview` always works. |
| `recipient` | string | `""` | Recipient for the bundle notification email. Empty falls back to `[transfer].recipient`; if both are empty, the CLI suggests `kaine.one@tuta.com` and requires explicit operator confirmation before sending. |
| `tier` | string | `"metrics"` | Bundle tier shown on the Nexus research status. The CLI takes the tier from `--tier`, which offers only `"metrics"`; the full tier needs a separate attestation. |

Admissibility enforcement (paper §6.3) is implemented in the research-submission code; there is no configuration key for it. Every bundle build auto-discovers the run(s) in the eval logs and runs both a completeness gate (contiguous ticks/seq, all expected streams present, no parse errors, no restart/multi-process signature) and a log-range sweep (every logged number within its declared range). If either check fails, the export is blocked by default. The only way to export an inadmissible run is the explicit `admissibility_override=True` plus a reason string at the call site (`--admissibility-override-reason "<why>"`), which is stamped into the bundle manifest.

### `[research_submission.claude_science]`

Claude Science export: reshape the same metrics-only research bundle into a Claude Science project folder. It is a thin adapter over the research-submission bundle builder and excludes conversation text, memories, the self-model, inner speech, and the raw bus archive by construction. Because it produces a folder intended for a cloud workbench, the export is governed as an external disclosure under guardian consent. It is exploratory only and never part of the deterministic verdict pipeline.

Operator path: `python -m kaine.research --claude-science`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Default is disabled. |

## `[research_event_log]`

Curated, privacy-filtered research event log for longitudinal analysis. Subscribes to a curated allowlist of bus streams and writes one privacy-filtered record per relevant event to an encrypted, daily-rotated JSONL sink under `data/evaluation/research_events/`. Every record passes `PrivacyFilter` plus per-type redaction before it is written, so the log never captures raw audio or video, transcripts, conversation content, memory text, the Eidolon self-model, or operator host/IP. Avatar coordinates are logged only as an opaque hash.

`research_events` is in the metrics-bundle allowlist, so an operator-initiated metrics research bundle may include it. This section is the only mechanism that makes it export-eligible.

Default is disabled. It runs independently of `[evaluation].enabled`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. |
| `log_dir` | string | `"data/evaluation/research_events"` | Directory for the curated log sink. Must stay under `data/evaluation/` to remain export-eligible. |
| `retention_days` | integer | `0` | Daily-rotated file retention window in days. `0` keeps every file (no age-based purge); a positive value purges older daily files. |

### `[research_event_log.raw_archive]`

Optional local-only raw bus archive. Never export-eligible. Tees verbatim bus events (including conversation content and transcripts) to `state/research/raw_bus_archive/`, a path outside `data/evaluation/` that the metrics bundle builder never reaches. Encrypted at rest like every other sink.

This is doubly gated: it requires `enabled = true` and both attestation flags set to `true`. With `enabled = true` but either attestation false, the consumer refuses to start with a `RawArchiveAttestationError`, mirroring the full-tier attestation gate in `kaine/research/submission.py`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. |
| `entity_privacy_attested` | boolean | `false` | Attestation: entity privacy considerations reviewed. Required alongside `bystander_consent_attested`. |
| `bystander_consent_attested` | boolean | `false` | Attestation: bystander consent for verbatim local capture obtained. Required alongside `entity_privacy_attested`. |
| `archive_dir` | string | `"state/research/raw_bus_archive"` | Storage path. Must remain outside `data/evaluation/`. |
| `retention_days` | integer | `0` | Daily-rotated file retention window in days. `0` keeps every file (no age-based purge). |

### `[research_event_log.external_utterances]`

Optional local-only external-speech recorder. Never export-eligible. Subscribes only to `lingua.external` and writes one record per `external_speech` event. The record contains the `text` field only; `user_input` (bystander speech) and all other payload fields are dropped. It never subscribes to `lingua.internal` or `lingua.out`, so inner speech is never recorded.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. |
| `log_dir` | string | `"state/research/external_utterances"` | Directory for the utterance log. |
| `retention_days` | integer | `0` | Daily-rotated file retention window in days. `0` keeps every file. |

### `[research_event_log.nexus_record]`

Optional local-only Nexus diagnostics recorder. Never export-eligible. Subscribes to the same diagnostics streams the Nexus bridge reads and writes the payload produced by `PrivacyFilter` with `dev_content_override=false` and numeric vectors removed, plus the stream name and entry id. Studies never enable it. Filter failures drop the event with a warning.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. |
| `log_dir` | string | `"data/nexus_record"` | Directory for the diagnostics log. |
| `retention_days` | integer | `0` | Daily-rotated file retention window in days. `0` keeps every file. |

## `[ignition_log]`

In-process log for studies that align workspace broadcasts to a playlist programme, chiefly the module-addition study (the code calls it the ignition study; see [the module-addition study](../15-experiments/ignition-study.md)). It records every successful workspace broadcast with programme position, audio-delivered position, coalition member ids and timestamps, candidate scores, and inhibition. No event payloads are recorded, so no conversation content, transcripts, video frames, or audio samples are persisted. The log is never on the bus, never reaches any module, and is encrypted at rest when state encryption is on. Files are never auto-purged.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Master gate. |
| `directory` | string | `"data/ignition"` | Directory for ignition-log files. |
