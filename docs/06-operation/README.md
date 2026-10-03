# Day-to-day operation

This page covers normal operation of a running KAINE instance: starting and stopping the cycle, changing the tick rate at runtime, enabling a module safely, and reading the predictive-signal dashboards. Read this after [first boot](../04-getting-started/first-boot.md).

## Starting and stopping

### Normal start

```bash
# Terminal 1 — Nexus dashboard
python -m kaine.nexus

# Terminal 2 — cognitive cycle (operator must be present)
export KAINE_CYCLE_OPERATOR_PRESENT=1
python -m kaine.cycle
```

Nexus binds to loopback by default. How to reach it, switch to token mode, and serve it over your tailnet is covered in [Opening Nexus](../05-nexus.md).

A fresh launch always clears any stale freeze left by a previous run; the entity always starts running.

The launch above is the operator-supervised path: a human is the safety net. KAINE also supports an unattended supervision mode: set `KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"`. An eight-condition gate checks the host before the cycle starts unattended; if the gate refuses, the cycle exits with code 6. The separate research-run path is covered in [Preservation and the safety net](../11-preservation.md) and [For researchers](../14-for-researchers.md).

### Freeze and resume

The diagnostics page has a "cycle control" panel with "freeze cycle" and "resume cycle" buttons. While frozen, the cycle stops ticking but the process stays up. A frozen state is not persisted across restarts; a fresh launch clears any stale freeze and the cycle starts running.

Freeze requests can come from several holders, which stack: `operator`, `spot`, `welfare`, `preserve`, `gestation` and `programme_end`. The dashboard "resume cycle" button releases only `operator` entries. Spot and preservation release their own entries. A `welfare`, `gestation` or `programme_end` freeze stays until you override it by name: the panel shows which holders remain and offers an "override … freeze" button that needs a second click to confirm. Each override is recorded, without content, in `state/cycle/override_audit.jsonl`. A fresh launch starts unfrozen.

### Normal stop

Press `Ctrl-C` in the cycle terminal. `CognitiveCycle.shutdown()` sets a stop event, lets the current tick finish, runs shutdown hooks — Hypnos cleans up adapter checkpoints and Mnemos flushes the short-term buffer — and returns. Modules shut down in order.

Do not `kill -9` the cycle process during a Hypnos pass. The Hypnos multi-phase pipeline is non-interruptible because partial voice-alignment adapter writes are unsafe. Wait for the rest cycle to finish, then stop.

### The organ sleeps when idle

The model server unloads the organ after `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` idle seconds in container and Quadlet deployments, or after `[lingua].model_server_sleep_idle_seconds` when KAINE launches the server natively. The default is 600; `-1` keeps the model loaded. While it sleeps the server holds neither the model nor its KV cache, so once the cycle stops the organ unloads within that timeout with no operator action. The next inference request reloads it, which takes a few seconds.

Health polling against `/v1/models` and `/props` does not wake the organ. The Nexus health board and the pre-boot Chat LLM row therefore report it as `up` and `asleep`. The pre-boot Organ content row sends a real completion, which wakes the server. If you override `KAINE_MODEL_SERVER_CMD`, pass `--sleep-idle-seconds` yourself.

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

### Dedicated headless host

For turning a Linux machine into an unattended 24/7 appliance — persistent performance profile, verified remote access before the headless switch, swap + Podman + linger reboot survival, and tailnet dashboard reachability without widening binds — see [A dedicated headless host](../07-deployment/headless-host.md). The procedure is host-generic; a Jetson Orin Nano Super worked example is included.

## Cycle rate control

The cycle rate can be changed at runtime without restarting:

- From the diagnostics page, use the "Cycle rate" control and confirm.
- Via API: `POST /diagnostics/cycle/rates {"processing_rate_hz": 10.0}`.

Nexus publishes a `cycle.set_rates` event on the `cycle.control` stream; the running cycle consumes it and applies the new rate. The endpoint also accepts `experiential_rate_hz`. The change is not persisted — on next start the cycle uses the TOML value.

The shipped `config/kaine.toml` defaults are `processing_rate_hz = 10.0` (100 ms per workspace tick) and `experiential_rate_hz = 3.333` Hz.

## Enabling a module safely

Every module enable is a deliberate supervised step. The shipped `config/kaine.toml` supplies the module defaults used below. With no profile selected, the loader applies the base-thesis `thesis_test` profile, which sets the module flags plus a few perception and voice settings. `config/kaine.operator.toml` always merges last and wins; the first-run wizard writes a full `[modules]` table there, so after the wizard its module choices replace the profile's.

The general procedure:

1. Fork the latest stored snapshot before you change anything. `POST /diagnostics/forks` requires an existing `parent_id`; it deep-copies that stored snapshot, it does not capture live state. Use the Fork/Merge panel on the diagnostics page or the API directly, and record the returned snapshot id.
2. Stop the cycle.
3. Verify dependencies for the module (see the table below).
4. Set `[modules].<name> = true` in your per-install overlay, `config/kaine.operator.toml`. Do not edit the tracked `config/kaine.toml` for per-install enables.
5. Restart the cycle with `KAINE_CYCLE_OPERATOR_PRESENT=1`.
6. Watch the diagnostics page — confirm the module appears in the modules grid with status `running`.

Module-specific prerequisites:

| Module | Prerequisites |
|---|---|
| `nous` | `[reasoning]` extra installed (`inferactively-pymdp`, `jax[cpu]`) |
| `mnemos` | Qdrant container up; Qdrant API key in `config/secrets.toml` |
| `lingua` | OpenAI-compatible model server serving `model_id` on `http://127.0.0.1:11434/v1`; `enable_thinking: false` honored via `chat_template_kwargs` |
| `audition` | `[audio]` extra installed; Speaches up on CPU with `medium.en` |
| `vox` | Chatterbox up; `predefined_voice_id` set to a valid filename |
| `topos` | `[internvideo]` extra installed; the pinned InternVideo-Next weights cached locally (DINOv2-small only when the per-frame fallback `encoder_backend = "dinov2"` is selected) |
| `hypnos` | `mnemos` enabled; optionally `thymos` and `phantasia` for full consolidation |
| `empatheia` | Qdrant container up |
| `phantasia` | `[worldmodel]` extra installed for the DreamerV3 backend; the shipped defaults are `backend = "dreamerv3"`, `engine = "jax"`, `training_enabled = true`, `persist_weights = true` |
| `praxis` | Shell whitelist is empty by default; fill it deliberately before enabling |
| `perception` | No extras; physical-XOR-virtual locus arbiter — `perception = false` is already in the shipped `[modules]` block, so set it to `true` in your overlay |
| `mundus` | The shipped `config/kaine.toml` already has `[mundus].enabled = true`. To enable the module, set `[modules].mundus = true` and export `KAINE_MUNDUS_OPERATOR_APPROVED=1`. The only shipped adapter is `stub` (transport-free); a Paracosmic virtual-world adapter is planned |

## Monitoring predictive signals

### Fatigue and sleep

The architecture makes sleep emergent rather than scheduled. Soma maintains a fatigue accumulator from *unexpected* substrate prediction error — error beyond a learned band — decaying slowly during operation. The learned band uses `expected_error_tau_s = 600` and `expected_error_band = 2.0`. Soma still reports raw `prediction_error` for the welfare monitor, and `soma.report` also includes `unexpected_error`. When the accumulator crosses `[soma].fatigue_maintenance_threshold` (default 100.0), a `soma.fatigue` event triggers Hypnos.

Monitor the fatigue chart on the diagnostics page. If it grows continuously without consolidation events, check that:

- Hypnos is enabled and initialized.
- `[hypnos.consolidation].fatigue_triggered = true`.
- Soma is publishing `soma.fatigue` events (visible in the health board).

`[hypnos].interval_seconds` (default 3600) is a maximum-interval safety net — Hypnos also fires that often if fatigue never crosses threshold.

### Oscillatory coherence

When `[oscillator].enabled = true` and the `[oscillator]` extra is installed, the PLV chart shows phase-locking values between module pairs over time.

High PLV between a pair of modules that co-produce a workspace event means their outputs are receiving a coherence bonus in Syneidesis scoring. The bonus is bounded by `[oscillator].coherence_ceiling` (default 1.25). Desynchronized modules are attenuated down to `[oscillator].coherence_floor` (default 0.8).

The oscillatory layer ships disabled (`[oscillator].enabled = false`) because it is empirically uncharacterized. Enable it only after the sidecar coherence observer has measured its effect on your deployment.

### A/B divergence

The A/B divergence metric quantifies the architecture's contribution to Lingua's output. The same model, the same input, two responses: one conditioned on the full workspace (persona + coalition + input) and one with no workspace conditioning (bare LLM). The cosine distance between the two response embeddings is the divergence.

Near-zero divergence means the workspace is not conditioning the language organ. If divergence drops unexpectedly:

- Check that the cycle is ticking and modules are broadcasting workspace events.
- Check that Lingua's `ContextAssembler` is receiving the coalition from Syneidesis (look for `lingua.external` events on the diagnostics stream).
- Check the evaluation sidecar is running (`[evaluation].enabled = true`).

### Forks, merges and the sleep cycle

A fork is a deep copy of an existing stored snapshot. `POST /diagnostics/forks` requires a `parent_id` and duplicates that snapshot; it does not capture live state. A fork copies Phantasia's encrypted weights when they exist; a restore installs them at that instance's own checkpoint path. Use a fork before any significant configuration change or module enable. Forks are stored under `state/forks/` inside the configured data root.

**Merge** combines two fork snapshots, using real TIES/DARE adapter merging whenever the `[training]` extra is installed (`[lifecycle].adapter_merger = "auto"`, the default — force `"ties_dare"` or `"fake"` to override auto-detection). The individuation boundary instrument on the evaluation tab quantifies whether a fork has developed statistically independent identity before merging.

Both operations are available from the diagnostics page under the Fork/Merge panel and via the API:

```text
POST /diagnostics/forks   {"parent_id": "<id>", "label": "..."}
POST /diagnostics/merges  {"snapshot_a_id": "<id>", "snapshot_b_id": "<id>"}
```

Optionally add `"world_model_from": "a"|"b"` to choose which parent supplies the Phantasia world model, and the `allow_unmerged_adapters` flag to keep the parents' adapters uncombined when a merge is refused (no real merger, or a merged adapter that failed its capability or abliteration checks). If both snapshots carry a Phantasia world model and you do not pass `world_model_from`, the API returns 409. The dashboard merge form's "world model from" choice sets the same field.

**Sleep cycle operationally:** Hypnos consolidation runs in a non-interruptible multi-phase pipeline. During consolidation the cycle continues running, but the Hypnos phase gate blocks other experiential ticks until consolidation completes. On the diagnostics page you will see the tick rate stall briefly while the phases run. Do not stop the cycle during this window.
