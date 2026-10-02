# The cognitive cycle

The cognitive cycle is KAINE's repeating async loop. It paces the system, reads events from active modules, selects what enters the global workspace, broadcasts conscious ticks, and issues intents. This page is for operators tuning timing, freezing, or rate control, and for contributors working on the cycle engine.

For the selection algorithm, see [The global workspace](./global-workspace.md). For sleep and maintenance, see [Sleep and maintenance](../10-sleep/README.md). For wider system architecture, see [Architecture](../02-architecture/README.md). For cycle and host settings, see [Core, cycle and host configuration](../appendix-a-configuration/core.md).

## Rates and timing

The cycle has two independently configurable rates.

| Parameter | Default | Config key |
|---|---|---|
| `processing_rate_hz` | 10.0 | `[cycle].processing_rate_hz` |
| `experiential_rate_hz` | 3.333 | `[cycle].experiential_rate_hz` |

`processing_rate_hz` is how often the tick loop fires: 10 Hz by default, an alpha-band sampling rate (100 ms per tick). Conscious access is slower: `experiential_rate_hz` (3.333 Hz at rest, the P3b band) sets how often a tick becomes a conscious broadcast, so the senses outrun awareness and several samples inform one update. The reference development host runs the tick loop with about 17 Hz of headroom.

`experiential_rate_hz` is how often a tick's snapshot is broadcast to `workspace.broadcast` and becomes conscious. The cycle tracks this with a fractional accumulator (`_experience_acc`): each tick adds `experiential_rate / processing_rate` to the accumulator; when it reaches `1.0`, a broadcast fires and `1.0` is subtracted, keeping the fractional carry. This keeps the long-run ratio exact when the two rates do not divide evenly. At most one broadcast happens per tick.

`CognitiveCycle.__init__` falls back to `experiential_rate_hz == processing_rate_hz` only when no value is supplied. The composition root at `kaine/cycle/__main__.py` and `config/kaine.toml` both default `experiential_rate_hz` to 3.333 Hz, the resting P3b conscious-access band, so at the default 10 Hz processing rate roughly one tick in three is broadcast. This lets faster senses outrun awareness. Setting the two rates equal restores one-tick-one-broadcast behavior. Setting `experiential_rate_hz` lower decouples background processing ticks further from conscious ticks.

The config and `cycle.set_rates` accept any positive value. Only [Soma](../09-modules/soma.md)'s `reduce_rate` advisory clamps the processing rate to [0.5, 20.0] Hz.

### Adaptive conscious access

`experiential_rate_hz` is the resting rate. With `[cycle.access_rate].enabled` — the shipped default — the cycle recomputes the broadcast rate for each tick from an **access drive** in [0, 1].

- **Tonic** drive: [Thymos](../09-modules/thymos.md) arousal above its resting baseline, scaled to [0, 1]. Arousal rises with perceptual prediction error, so failed predictions raise it.
- **Phasic** drive: the most salient module report on the tick above `salience_floor` (0.5), scaled to [0, 1] and held as a peak that decays with time constant `phasic_decay_s` (1 subjective second). Events from `cycle` and `syneidesis` are not module reports and do not count.

The drive is the larger of the two. The tick's broadcast rate is `resting + (processing − resting) × drive`: 3.333 Hz when calm, one broadcast per processing tick at full drive. The operator's rate control and fork timing profiles set the resting rate. The adaptive rate never goes below the resting rate or above the processing rate.

Every `cycle.tick` event carries the tick's effective `experiential_rate_hz` and `access_drive`. `runtime.json` carries `experiential_rate_effective_hz` and `access_drive` next to the resting rate. Only conscious access adapts: the processing rate stays at its configured value. `enabled = false` gives the fixed resting rate.

### Time dilation

`processing_rate_hz` and `experiential_rate_hz` are **subjective** Hz rates: they describe the felt tick period, not necessarily the real one. The `[cycle].time_scale` key (default `1.0`) controls how the entity's subjective clock runs relative to wall-clock time:

| `time_scale` | Meaning |
|---|---|
| `0` | Frozen. The subjective clock stops. This reuses the pause/freeze path; the cycle does not add a second freeze mechanism. Setting `time_scale = 0` with `auto_time_scale = true` is a configuration error and refuses boot. |
| `1.0` | Real-time, the shipped default. Behavior is byte-identical to no clock injection. |
| `< 1.0` | Slower subjective time. |
| `> 1.0` | Faster subjective target. The cycle attempts the faster real tick rate and records shortfall honestly as slip. |

`EntityClock` (`kaine/entity_clock.py`) is the single shared subjective clock. Every module that times a cognitive process derives its "now" and durations from one injected `EntityClock` instance, so one `time_scale` knob dilates the whole mind coherently. `EntityClock.wall()` is the real monotonic clock, used only for slip and health measurement. `EntityClock.now()` is subjective time (`origin + wall_elapsed * scale`). `EntityClock.period(hz)` converts a subjective-Hz rate into the real seconds-per-tick budget the cycle paces against: `1 / (hz * scale)`. That is what `CognitiveCycle.tick()` uses to compute `target_ms` each tick.

Infrastructure timers that must track real wall-clock time regardless of subjective rate, such as the Spot watchdog, preservation monitor, and network timeouts, do not use this clock.

`CognitiveCycle.pacing_stats` is the honest pacing report exposed via the `pacing_stats` property and surfaced in Nexus. It uses a rolling 32-tick window of real per-tick wall time versus target budget, reporting:

- `target_rate_hz` = `processing_rate_hz * time_scale`
- `achieved_rate_hz` derived from the mean real tick duration
- `mean_slip_ms` and `max_slip_ms`
- `overrunning`, true when the achieved rate falls more than 1% below target

This makes a `time_scale > 1` dilation visible rather than silently throttled.

### Automatic time dilation

`[cycle].auto_time_scale` (default `false`) turns on automatic time-scale adjustment. The cycle measures the busy fraction of each tick as an exponential moving average over `auto_time_scale_window_s` of wall time. If utilization stays above `auto_time_scale_high` for `auto_time_scale_dwell_s`, `time_scale` drops in one step to bring utilization toward `auto_time_scale_target`. If it stays below `auto_time_scale_low` for three consecutive dwells, `time_scale` rises by at most ×1.25 per step. The controller never exceeds the configured `time_scale` ceiling, never falls below `auto_time_scale_floor`, waits at least one dwell between changes, and is disabled in deterministic mode. An invalid threshold combination or `time_scale = 0` with auto enabled refuses boot with a configuration error.

Every change publishes a `cycle.time_scale` event with `from`, `to`, `reason` (`overload` or `headroom`), `utilization`, and `window_s`. Each `cycle.tick` payload and each ignition-log record carries `time_scale`. The run manifest records the timing settings under `timing`. The `pacing` block of `runtime.json` shows `time_scale`, `auto_time_scale`, and `time_scale_changes`.

Soma's `reduce_rate` regulation still lowers the processing rate when it senses overload. That lowers utilization, and automatic dilation may then raise the scale back toward the ceiling.

## Tick sequence

```mermaid
flowchart TD
    A[Start tick] --> B[Drain cycle.control events]
    B --> C[Drain soma.out regulation]
    C --> D[Read active module streams]
    D --> E[Sort events by source, type, entry_id]
    E --> F[Refresh affect observer and access rate]
    F --> G[Syneidesis.select]
    G --> H{Is experiential tick?}
    H -- no --> O[Publish cycle.tick latency]
    H -- yes --> I[Publish workspace.broadcast]
    I --> J[Volition.select snapshot]
    J --> K[Publish intents on volition.out]
    K --> L[Publish volition.proposal_outcome on volition_feedback.out]
    L --> O
    O --> P[Sleep remaining budget]
    P --> A
```

### Drain control events

`consume_control_events()` reads up to 32 entries from `cycle.control` using a persistent cursor. Each `cycle.set_rates` event applies updated `processing_rate_hz` and/or `experiential_rate_hz`. Both must be positive. On success the cycle publishes `cycle.rates` to `cycle.out`. Invalid payloads are logged and skipped without disrupting the loop.

### Drain soma regulation

`consume_soma_regulation()` reads up to 32 `soma.regulation` events from `soma.out`.

| Action | Effect |
|---|---|
| `reduce_rate` | Multiply `processing_rate` by 0.8, clamped to [0.5, 20.0] Hz |
| `shed_module` | Call `registry.request_shed_low_priority()` if available |
| `request_maintenance` | Latch `cycle.maintenance_requested = True` as an advisory signal. Hypnos observes the `request_maintenance` regulation event directly on `soma.out`; nothing else reads this flag to drive behaviour. |

Unknown action values are silently ignored. All advisories are advisory only: the cycle acts within safe bounds, logs, and continues.

### Read module streams

The main read path is now one round-trip `read_entries_block` for all active module streams returned by `registry.active_streams()`. A per-stream `asyncio.gather` is used only as a fallback. Each stream is read with `block_ms=0` (non-blocking) and `count=100` (configurable). The per-stream cursor advances to the last entry ID scanned, decodable or not, so a batch of undecodable entries moves the cursor past itself instead of stalling the stream. Read failures increment a per-stream error counter but do not stop the loop.

On a production boot the entrypoint constructs the cycle with `seed_cursors_to_tail=true`. Every stream cursor is seeded to the stream tail before the first read, so an in-run process restart against a live Redis replays nothing that predates the boot, including stale soma rate advisories. Library or test construction reads from the beginning.

### Selection

`syneidesis.select(events, context)` receives the event list plus a context dict containing `tick_index`, `is_experiential`, and (when the oscillatory layer is enabled) `phases` — a dict mapping module names to their current oscillator phase. Before selection, the events are sorted by `(source, type, entry_id)`, the affect observer refreshes, and the access rate updates. The function returns a `WorkspaceSnapshot`.

### Broadcast

If the tick is experiential and selection succeeded, the cycle calls `bus.publish_workspace(payload)` on `workspace.broadcast`. The payload mirrors the `WorkspaceSnapshot`: tick index, inhibited flag, selected events (with `entry_id`, `source`, `type`, `salience`, `payload`, `timestamp`, `causal_parent`), per-event salience scores, and metadata including PLV coherence when the oscillatory layer is on.

Only `source="syneidesis"` may call `publish_workspace`. Any other source raises `ReservedStreamError`.

### Volition and proposal outcomes

After a successful broadcast the cycle calls `Volition.select(snapshot)`. Volition applies the inhibition gate first. Inhibited snapshots return no intents.

Each returned intent is published to `volition.out` with event type `intent.speak`, `intent.think`, `intent.act`, or `intent.rest`. The cycle then publishes any `proposal_outcome` values returned by the policy to `volition_feedback.out` as `volition.proposal_outcome` events.

Proposal outcomes are generated only when the action-selection policy includes the `NousProposalSource` wrapper, which requires [Nous](../09-modules/nous.md) to be enabled. With no profile selected, the loader applies the `thesis_test` profile, and that profile has `nous = false`, so no proposal outcomes are produced by default.

The cycle never invokes effectors directly. [Lingua](../09-modules/lingua.md), [Praxis](../09-modules/praxis.md), [Perception](../09-modules/perception.md), [Mundus](../09-modules/mundus.md), and [Hypnos](../09-modules/hypnos.md) subscribe to `volition.out` and realize intents independently. Hypnos accepts `intent.rest` as a request to rest.

### Latency telemetry

Every tick publishes a `cycle.tick` event to `cycle.out`:

| Field | Type | Meaning |
|---|---|---|
| `tick_index` | int | tick counter, 0-based |
| `wall_duration_ms` | float | actual tick wall time |
| `target_duration_ms` | float | `1000 / (processing_rate_hz * time_scale)` |
| `slip_ms` | float | `max(0, wall - target)` |
| `is_experiential` | bool | did this tick broadcast? |
| `error` | bool | did Syneidesis raise? |
| `processing_rate_hz` | float | current processing rate |
| `experiential_rate_hz` | float | current effective experiential rate |
| `access_drive` | float | current access drive in [0, 1] |
| `time_scale` | float | current time scale |

Salience is 0.05 for clean ticks and 0.5 for error ticks. [Soma](../09-modules/soma.md) subscribes to `cycle.out` to track latency as part of interoceptive prediction error.

## Operator freeze

`kaine/cycle/control_state.py`

The operator can freeze the cycle by writing `state/cycle/control.json`:

```json
{
  "frozen": true,
  "frozen_at": "2026-06-06T12:00:00+00:00",
  "reason": "infrastructure maintenance",
  "source": "operator",
  "stack": [
    {"source": "operator", "reason": "infrastructure maintenance",
     "frozen_at": "2026-06-06T12:00:00+00:00"}
  ]
}
```

The freeze is a stack of `{source, reason, frozen_at}` entries. The `stack` is authoritative; the top-level `frozen`, `frozen_at`, `reason`, and `source` fields are a legacy view mirroring the top of the stack. Older single-slot files are promoted to a one-entry stack on read. Sources stack independently: a Spot recovery pops only Spot's own entry, so a welfare pause underneath survives supervisor recovery and can be lifted only by an operator stand-down or an explicit welfare stand-down. The cycle resumes only when the stack is empty.

A freeze-watch task in the cycle entrypoint polls this file and calls `cycle.pause()` and `cycle.resume()` to match the commanded state. `pause()` clears an `asyncio.Event`; `run_forever` blocks on `await self._paused.wait()`, so no ticks fire while the event is clear. On freeze, the watch snapshots the desired perception flags and suspends them for non-gestation freezes; a gestation-only freeze keeps perception on. On resume it writes the snapshot back, so a freeze/resume cycle never leaves the entity deaf or blind.

Freeze suspends the entity's subjective clock while operators repair infrastructure. It is not a shutdown. The file contains only operational fields: freeze entries with ISO timestamps and optional reason strings. It never contains sensory content.

The Nexus `POST /diagnostics/cycle/freeze` endpoint writes this file. The `unfreeze` function atomically replaces the file with a `CycleControl()` whose fields are `frozen:false`, `frozen_at:null`, `reason:null`, `source:"operator"`, and `stack:[]`.

```mermaid
stateDiagram-v2
    [*] --> Running : boot (operator present)
    Running --> Frozen : freeze() — paused.clear()
    Frozen --> Running : unfreeze() — paused.set()
    Running --> Shutdown : shutdown()
    Frozen --> Shutdown : shutdown()
    Shutdown --> [*]
```

## Rate control API

Bus-driven rate changes use the `cycle.control` stream. Publish a `cycle.set_rates` event:

```python
Event(
    source="operator",
    type="cycle.set_rates",
    payload={"processing_rate_hz": 5.0, "experiential_rate_hz": 1.0},
    salience=0.5,
    timestamp=datetime.now(timezone.utc),
)
```

The cycle acknowledges by publishing `cycle.rates` to `cycle.out` with the new values. Rates persist for the process lifetime; they are not written to `config/kaine.toml`.

## Hooks

`CycleHooks` supports callbacks for three lifecycle events:

| Event | Fired by | Typical use |
|---|---|---|
| `pause` | `cycle.pause()` | Module suspension |
| `resume` | `cycle.resume()` | Module reactivation |
| `shutdown` | `cycle.shutdown()` | Graceful resource release |

Hooks are awaited in registration order. A hook that raises is logged and skipped; later hooks always run.

## Phase collection

When `[oscillator].enabled = true` in `config/kaine.toml` (see [Core, cycle and host configuration](../appendix-a-configuration/core.md)), the cycle sets `collect_phases = True`. Before passing events to Syneidesis each tick, `_collect_module_phases()` calls `module.phase()` on every module that exposes it via `registry.all_modules()`. The resulting dict is passed in `context['phases']` to `Syneidesis.select()`. Modules without an oscillator return the neutral phase.

When the layer is disabled, `_collect_module_phases()` is never called and `context['phases']` is absent, giving zero per-tick overhead.

## Configuration reference

All knobs live in `config/kaine.toml` (see [Core, cycle and host configuration](../appendix-a-configuration/core.md)):

```toml
[cycle]
processing_rate_hz = 10.0
experiential_rate_hz = 3.333
time_scale = 1.0
auto_time_scale = false
auto_time_scale_window_s = 30.0
auto_time_scale_target = 0.85
auto_time_scale_high = 0.95
auto_time_scale_low = 0.6
auto_time_scale_dwell_s = 10.0
auto_time_scale_floor = 0.1

[cycle.access_rate]
enabled = true
salience_floor = 0.5
phasic_decay_s = 1.0
# baseline_arousal is accepted; when absent it defaults to Thymos's baseline_arousal.

[oscillator]
enabled = false
population_size = 16
plv_window = 10
coherence_floor = 0.8
coherence_ceiling = 1.25
```

The `[oscillator]` section also accepts `beta`, `threshold`, and `base_drive`. Their defaults are set in `config/kaine.toml`.

Dynamic rate changes via the `cycle.control` stream override the `[cycle]` values for the current process. Only Soma's `reduce_rate` advisory clamps the processing rate to [0.5, 20.0] Hz.

## Key files

| File | Role |
|---|---|
| `kaine/cycle/engine.py` | `CognitiveCycle` — tick loop, rate control, Soma consumer |
| `kaine/cycle/control_state.py` | Freeze state serialization — `CycleControl`, `freeze()`, `unfreeze()` |
| `kaine/cycle/__main__.py` | Entrypoint — assembles modules, starts freeze-watch task |
| `kaine/cycle/types.py` | `TickResult`, `WorkspaceSnapshot` dataclasses |
| `kaine/cycle/protocols.py` | `CycleHook`, `ModuleRegistryProtocol`, `SyneidesisProtocol` |
| `kaine/entity_clock.py` | Shared subjective clock |
| `state/cycle/control.json` | Runtime freeze state (operator-written) |
