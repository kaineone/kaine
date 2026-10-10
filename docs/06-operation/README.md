# Day-to-day operation

This page covers normal operation of a running KAINE instance: starting and stopping the cycle, changing its rates at runtime, enabling a module, and reading the dashboards. Read it after [first boot](../04-getting-started/first-boot.md).

## Starting and stopping

### Normal start

```bash
# Terminal 1: the Nexus dashboard
python -m kaine.nexus

# Terminal 2: the cognitive cycle (an operator is present)
export KAINE_CYCLE_OPERATOR_PRESENT=1
python -m kaine.cycle
```

Nexus binds to loopback by default. How to reach it, switch to token mode, and serve it over your tailnet is covered in [Opening Nexus](../05-nexus.md).

A fresh launch clears any stale freeze left by a previous run, so the entity always starts running.

The launch above is the operator-supervised mode, in which a person watches the run. KAINE also has an unattended supervision mode, selected with `KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"` (the environment variable takes precedence). An eight-condition gate checks the host before the cycle starts unattended, and if the gate refuses, the cycle exits with code 6. Selecting unattended mode together with research mode or `KAINE_CYCLE_OPERATOR_PRESENT=1` is a configuration error. The research mode is covered in [Preservation](../11-preservation.md) and [For researchers](../14-for-researchers.md).

### Freeze and resume

The diagnostics page has a "cycle control" panel with "freeze cycle" and "resume cycle" buttons. While frozen, the cycle stops ticking but the process stays up. A frozen state is not persisted across restarts; a fresh launch clears any stale freeze and the cycle starts running.

Freeze requests can come from several holders, which stack: `operator`, `spot`, `welfare`, `preserve`, `gestation` and `programme_end`. The dashboard "resume cycle" button releases only `operator` entries. Spot and preservation release their own entries. A `welfare`, `gestation` or `programme_end` freeze stays until you override it by name: the panel shows which holders remain and offers an "override … freeze" button that needs a second click to confirm. Each override is recorded, without content, in `state/cycle/override_audit.jsonl`. A fresh launch starts unfrozen.

### Normal stop

Press `Ctrl-C` in the cycle terminal. The cycle stops ticking, each module's `shutdown()` runs in turn (Phantasia, for example, saves its weights), and the bus connection closes.

Do not `kill -9` the cycle process during a Hypnos sleep. Hypnos's sleep is non-interruptible, and when voice alignment is enabled a killed process can leave a partly written adapter. Wait for the sleep to finish, then stop.

### The organ sleeps when idle

The model server unloads the organ after `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` idle seconds in container and Quadlet deployments, or after `[lingua].model_server_sleep_idle_seconds` when KAINE launches the server natively. The default is 600, and `-1` keeps the model loaded. While it sleeps the server holds neither the model nor its KV cache, so once the cycle stops the organ unloads within that timeout with no operator action. The next inference request reloads it, which takes a few seconds. On the reference host, an asleep containerized organ holds about 210 MiB of VRAM (the CUDA context only) against several GB awake; check the release with `nvidia-smi`.

Health polling against `/health`, `/v1/models` and `/props` does not wake the organ. The Nexus health board and the pre-boot Chat LLM row therefore report it as `up` and `asleep`. The pre-boot Organ content row sends a real completion, which wakes the server. If you override `KAINE_MODEL_SERVER_CMD`, pass `--sleep-idle-seconds` yourself.

### Service containers

```bash
# Start
docker compose -f compose/redis.yml up -d
docker compose -f compose/qdrant.yml up -d

# Stop (keep data volumes)
docker compose -f compose/redis.yml down
docker compose -f compose/qdrant.yml down

# Stop and delete volumes (destructive: erases the bus AOF and the memory store)
docker compose -f compose/redis.yml down -v
docker compose -f compose/qdrant.yml down -v
```

### Dedicated headless host

To turn a Linux machine into an unattended host that runs around the clock, see [A dedicated headless host](../07-deployment/headless-host.md). It covers a persistent performance profile, verifying remote access before switching to headless, surviving reboots with swap, Podman and user lingering, and reaching the dashboard over a tailnet without widening the binds. The procedure works on any Linux host and includes a Jetson Orin Nano Super worked example.

## Cycle rates

The cycle has two rates. The processing rate, `[cycle].processing_rate_hz` (10.0 by default, a tick every 100 ms), is the rate at which every active module's stream is read and scored. The access rate is the rate of broadcast ticks, the processing ticks on which the cycle produces a broadcast. Its resting value is `[cycle].experiential_rate_hz` (3.333 by default, one broadcast every third processing tick). With `[cycle.access_rate].enabled = true` (the default), the access rate rises toward one broadcast per processing tick with the larger of two drives: tonic arousal above baseline, and a phasic input from the most salient report that carries a categorical alert (payload `alert` true) above `salience_floor`, decaying over `phasic_decay_s`. Graded reports without an alert do not raise it, so with no alert the rate rests at about 3.3 Hz. See [The cognitive cycle](../08-cognitive-cycle/README.md) for the details.

You can change the processing rate and the resting access rate at runtime without restarting:

- On the diagnostics page, use the "Cycle rate" control and confirm.
- Through the API: `POST /diagnostics/cycle/rates {"processing_rate_hz": 10.0}`. The endpoint also accepts `experiential_rate_hz`, and it requires the operator token unless Nexus runs with open access.

Nexus publishes a `cycle.set_rates` event on the `cycle.control` stream, and the running cycle applies it. The change is not persisted, so the next start uses the configured values.

## Enabling a module safely

Enable a module as a deliberate, supervised step. The shipped `config/kaine.toml` supplies the module defaults used below. With no profile selected, the loader applies the base-thesis `thesis_test` profile, which sets the module flags and a few perception, language and action settings. `config/kaine.operator.toml` always merges last and wins. The first-run wizard writes a full `[modules]` table there, so after the wizard its module choices replace the profile's.

The general procedure:

1. Fork the latest stored snapshot before you change anything. `POST /diagnostics/forks` requires an existing `parent_id` and deep-copies that stored snapshot; it does not capture live state. Use the Fork/Merge panel on the diagnostics page or the API directly, and record the returned snapshot id.
2. Stop the cycle.
3. Verify dependencies for the module (see the table below).
4. Set `[modules].<name> = true` in your per-install overlay, `config/kaine.operator.toml`. Do not edit the tracked `config/kaine.toml` for per-install enables.
5. Restart the cycle with `KAINE_CYCLE_OPERATOR_PRESENT=1`.
6. On the diagnostics page, confirm that the module appears in the modules grid with status `running`.

Module-specific prerequisites:

| Module | Prerequisites |
|---|---|
| `nous` | `[reasoning]` extra installed (`inferactively-pymdp`, `jax[cpu]`) |
| `mnemos` | Qdrant container up; Qdrant API key in `config/secrets.toml` |
| `lingua` | OpenAI-compatible model server serving `model_id` on `http://127.0.0.1:11434/v1`; `enable_thinking: false` honored via `chat_template_kwargs` |
| `audition` | `[audio]` extra installed; Speaches up on CPU with `medium.en` |
| `vox` | Chatterbox up; `predefined_voice_id` set to a valid filename |
| `topos` | `[internvideo]` extra installed; the pinned InternVideo-Next weights cached locally (DINOv2-small only when the per-frame fallback `encoder_backend = "dinov2"` is selected) |
| `hypnos` | None. Fatigue-triggered sleep runs in the base-thesis form without Mnemos; its consolidation phases do work only once Mnemos and Phantasia are enabled, and the affective reset acts on Thymos |
| `empatheia` | Qdrant container up |
| `phantasia` | `[worldmodel]` extra installed for the DreamerV3 backend; the shipped defaults are `backend = "dreamerv3"`, `engine = "jax"`, `training_enabled = true`, `persist_weights = true` |
| `praxis` | Shell whitelist is empty by default; fill it deliberately before enabling |
| `perception` | No extras. It arbitrates whether the senses come from the physical or the virtual locus, never both. The shipped `[modules]` block has `perception = false`, so set it to `true` in your overlay |
| `mundus` | The shipped `config/kaine.toml` already has `[mundus].enabled = true`. To enable the module, set `[modules].mundus = true` and export `KAINE_MUNDUS_OPERATOR_APPROVED=1`. The only shipped adapter is the transport-free `stub`; a Paracosmic virtual-world adapter is planned |

## Monitoring

### Fatigue and sleep

Sleep is triggered by fatigue. Soma keeps a fatigue accumulator fed by unexpected substrate prediction error, the part of the error beyond a learned band, and the accumulator decays slowly (`[soma].fatigue_decay_per_s`, 0.01). The band follows the expected error over `expected_error_tau_s` (600 entity seconds) and admits `expected_error_band` (2.0) spreads above it. Soma still reports its raw `prediction_error`, and `soma.report` also carries `unexpected_error`. When the accumulator crosses `[soma].fatigue_maintenance_threshold` (100.0), a `soma.fatigue` event triggers Hypnos.

Watch the fatigue chart on the diagnostics page. If fatigue grows continuously and no sleep follows, check that:

- Hypnos is enabled and initialized.
- `[hypnos.consolidation].fatigue_triggered = true`.
- Soma is publishing `soma.fatigue` events (visible in the health board).

`[hypnos].interval_seconds` (3600 by default) is a maximum interval: Hypnos also sleeps that often when fatigue never crosses the threshold.

### Oscillatory coherence

When `[oscillator].enabled = true` and the oscillator extra is installed, the PLV chart shows, for each broadcast, the phase-locking value of the modules competing in it. Syneidesis then multiplies each candidate's score by a coherence factor for its source module, between `[oscillator].coherence_floor` (0.8) for a desynchronized module and `[oscillator].coherence_ceiling` (1.25) for a phase-locked one.

The oscillatory layer ships disabled (`[oscillator].enabled = false`) because its effect has not been characterized, and the planned experiments run without it. Enable it only after the sidecar coherence observer has measured its effect on your deployment.

### A/B divergence

The A/B divergence observer pairs each external utterance of Lingua with a second inference from the same model and endpoint under a bare assistant prompt with no workspace content. The divergence is one minus the cosine similarity of the two responses' embeddings. It is a diagnostic of whether the workspace conditions the language organ, and the planned test does not use it.

A divergence near zero means the workspace is not conditioning the organ. If it drops unexpectedly:

- Check that the cycle is ticking and modules are broadcasting workspace events.
- Check that Lingua's `ContextAssembler` is receiving the coalition from Syneidesis (look for `lingua.external` events on the diagnostics stream).
- Check the evaluation sidecar is running (`[evaluation].enabled = true`).

### Forks, merges and the sleep cycle

A fork is a deep copy of an existing stored snapshot. `POST /diagnostics/forks` requires a `parent_id` and duplicates that snapshot without capturing live state. A fork copies Phantasia's encrypted weights when they exist; a restore installs them at that instance's own checkpoint path. Use a fork before any significant configuration change or module enable. Forks are stored under `state/forks/` inside the configured data root.

A merge combines two fork snapshots. It uses real TIES/DARE adapter merging whenever the training extra is installed (`[lifecycle].adapter_merger = "auto"`, the default); set `"ties_dare"` or `"fake"` to override the detection. The fork merge gate uses the shared divergence verdict, which includes the individuation ledger latch. Fork-point references are not built yet, so forks with enough lived time, or with unknown lived time, are preserved instead of merged.

Both operations are available from the diagnostics page under the Fork/Merge panel and via the API:

```text
POST /diagnostics/forks   {"parent_id": "<id>", "label": "..."}
POST /diagnostics/merges  {"snapshot_a_id": "<id>", "snapshot_b_id": "<id>"}
```

Optionally add `"world_model_from": "a"|"b"` to choose which parent supplies the Phantasia world model, and the `allow_unmerged_adapters` flag to keep the parents' adapters uncombined when a merge is refused (no real merger, or a merged adapter that failed its capability or abliteration checks). If both snapshots carry a Phantasia world model and you do not pass `world_model_from`, the API returns 409. The dashboard merge form's "world model from" choice sets the same field.

Hypnos sleep is non-interruptible. The cycle keeps running during a sleep while perception pauses, forward-model adaptation is suspended in the predictive processors, and affect and drives return to baseline (see [Sleep](../10-sleep/README.md)). Do not stop the cycle while a sleep is running.
