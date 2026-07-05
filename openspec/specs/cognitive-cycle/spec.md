# cognitive-cycle Specification

## Purpose
TBD - created by archiving change cognitive-cycle. Update Purpose after archive.
## Requirements
### Requirement: Cycle runner with pacing
The cognitive cycle SHALL run as an async loop that targets a configurable
processing rate (Hz). Each tick SHALL collect events, invoke Syneidesis,
optionally broadcast, and record latency. The cycle SHALL be startable,
pausable, resumable, and shutdownable through explicit API calls.

#### Scenario: Tick honors processing rate target
- **WHEN** the cycle is configured at 5 Hz (200 ms per tick) and ticks for
  one second under no load
- **THEN** the cycle completes between 4 and 6 ticks in that second

#### Scenario: Pause stops ticks until resume
- **WHEN** the cycle is running and `pause()` is awaited
- **THEN** no further ticks begin until `resume()` is awaited

#### Scenario: Shutdown drains and exits
- **WHEN** `shutdown()` is awaited
- **THEN** the run loop returns and any pending Soma latency events are
  flushed to the bus

### Requirement: Independent processing and experiential rates
The cycle SHALL support a processing rate and an experiential broadcast
rate as independent parameters. When the experiential rate is lower than
the processing rate, the cycle SHALL still tick at the processing rate but
SHALL only promote a fraction of snapshots to experiential broadcasts in
the ratio of experiential rate to processing rate.

#### Scenario: Half-rate experiential broadcasts
- **WHEN** processing rate is 10 Hz and experiential rate is 5 Hz, and the
  cycle runs for 100 ticks
- **THEN** between 45 and 55 ticks publish to `workspace.broadcast` with
  `is_experiential=True`

#### Scenario: Equal rates broadcast every tick
- **WHEN** processing rate equals experiential rate
- **THEN** every tick publishes an experiential broadcast

### Requirement: Graceful module absence
The cycle SHALL skip any registered module that has no new events on its
stream this tick. The cycle SHALL NOT block on any individual module's
read and SHALL continue running if a module raises during processing.

#### Scenario: Quiet module skipped silently
- **WHEN** module `chronos` has no new events since the last tick
- **THEN** the cycle's collected event set contains no entries from
  `chronos.out` and no error is raised

#### Scenario: Erroring module does not stop the cycle
- **WHEN** the bus raises for `bad_module.out` on a tick
- **THEN** the cycle increments a per-module error counter, emits a
  latency event with `error=True`, and proceeds with the next tick

### Requirement: Tick latency published as cycle output
On every tick the cycle SHALL publish a tick-latency event to its own
`cycle.out` stream (source `cycle`) containing `tick_index`,
`wall_duration_ms`, `target_duration_ms`, `slip_ms`, and a boolean
`is_experiential`. Soma subscribes to `cycle.out` like any other consumer.
The cycle SHALL claim source `syneidesis` only when calling
`bus.publish_workspace`.

#### Scenario: Slip recorded when tick overruns
- **WHEN** a tick takes 350 ms with a 200 ms target
- **THEN** the latency event has `slip_ms >= 150` and the next tick begins
  immediately rather than after a negative sleep

### Requirement: Cycle hooks for lifecycle integration
The cycle SHALL expose a hooks protocol allowing other modules to register
callbacks for `on_pause`, `on_resume`, and `on_shutdown`. Hooks SHALL be
awaited in registration order; a hook raising SHALL log a warning but
SHALL NOT prevent later hooks from running.

#### Scenario: Pause hook fires before pause completes
- **WHEN** a module registers an `on_pause` hook and the cycle's `pause()`
  is awaited
- **THEN** the hook callable is awaited before `pause()` returns

### Requirement: Bus-driven rate control surface
The cognitive cycle SHALL subscribe to a `cycle.control` stream and,
on each event with type `cycle.set_rates`, SHALL update its
`processing_rate_hz` and/or `experiential_rate_hz` from the event's
payload (using whichever of `processing_rate_hz` or
`experiential_rate_hz` keys are present). After applying the update,
the cycle SHALL publish a `cycle.rates` event reflecting the new
state.

#### Scenario: cycle.set_rates with only processing_rate_hz
- **WHEN** an event with payload `{"processing_rate_hz": 5.0}`
  arrives on `cycle.control` while the cycle is running
- **THEN** the cycle's `processing_rate_hz` becomes `5.0` and a
  `cycle.rates` event is published whose payload reports the new
  value

#### Scenario: cycle.set_rates with both rates
- **WHEN** an event with payload
  `{"processing_rate_hz": 10.0, "experiential_rate_hz": 2.0}` arrives
- **THEN** both rates are updated and the published `cycle.rates`
  event reflects both

#### Scenario: Invalid rate value rejected without disrupting cycle
- **WHEN** an event arrives with `processing_rate_hz=-1`
- **THEN** the cycle's rate is NOT updated and the cycle continues
  ticking; a `cycle.rates` event is NOT published for the failed
  update

### Requirement: Experiential broadcast ratios accurate over many ticks
The cycle's experiential accumulator SHALL maintain accurate
broadcast ratios across an arbitrary number of ticks. Over 1000
ticks at the configured ratio R = experiential_rate / processing_rate,
the number of experiential broadcasts SHALL be within ±2 of
`1000 * R`.

#### Scenario: 3-to-1 ratio over 30 ticks broadcasts 10±2
- **WHEN** processing_rate_hz=3.0 and experiential_rate_hz=1.0 and
  the cycle runs 30 ticks
- **THEN** the count of experiential broadcasts is between 8 and 12

#### Scenario: 100-to-1 ratio over 200 ticks broadcasts 2±2
- **WHEN** processing_rate_hz=100.0 and experiential_rate_hz=1.0 and
  the cycle runs 200 ticks
- **THEN** the count of experiential broadcasts is between 0 and 4

### Requirement: Boot-time secrets merge for the cycle config

The cognitive cycle's boot-time configuration loader SHALL merge
`config/secrets.toml` into the configuration consumed by the module registry,
before `build_registry` runs. The Qdrant API key SHALL be resolved with the
precedence `KAINE_QDRANT_API_KEY` environment variable first, then
`config/secrets.toml` `[qdrant].api_key`, and the resolved value SHALL be
injected into the in-memory `[qdrant].api_key` section of **every qdrant-backed
consumer** so each module's factory forwards it to the Qdrant client. The
qdrant-backed consumers are at minimum `[mnemos.qdrant]` and
`[empatheia.qdrant]`.

The loader SHALL NOT require the key to be present in the git-tracked
`config/kaine.toml`. For each consumer section, when a key is already present
(e.g. `[mnemos.qdrant].api_key` or `[empatheia.qdrant].api_key` in
`config/kaine.toml`), the loader SHALL leave that section's key intact rather
than overwrite it. When no key is resolvable from the environment or
`config/secrets.toml`, the loader SHALL NOT inject an empty value into any
consumer section, so that a qdrant-backed module surfaces its existing explicit
error. If `config/secrets.toml` exists and is group- or world-readable, the
loader SHALL emit the same file-mode warning the bus config loader emits.

#### Scenario: Key only in secrets.toml reaches Mnemos

- **WHEN** `config/secrets.toml` contains `[qdrant].api_key` and no
  `KAINE_QDRANT_API_KEY` env var is set and `config/kaine.toml` has no
  `[mnemos.qdrant].api_key`
- **THEN** the loaded cycle config has `mnemos.qdrant.api_key` equal to the
  secrets-file value
- **AND** a qdrant-backed Mnemos constructs without raising the missing-key
  error

#### Scenario: Key only in secrets.toml reaches Empatheia

- **WHEN** `config/secrets.toml` contains `[qdrant].api_key` and no
  `KAINE_QDRANT_API_KEY` env var is set and `config/kaine.toml` has no
  `[empatheia.qdrant].api_key`
- **THEN** the loaded cycle config has `empatheia.qdrant.api_key` equal to the
  secrets-file value
- **AND** a qdrant-backed Empatheia constructs without raising the missing-key
  error

#### Scenario: Environment variable takes precedence over secrets file

- **WHEN** both `KAINE_QDRANT_API_KEY` is set and `config/secrets.toml`
  `[qdrant].api_key` is present with a different value
- **THEN** the loaded cycle config has both `mnemos.qdrant.api_key` and
  `empatheia.qdrant.api_key` equal to the environment-variable value

#### Scenario: Explicit per-consumer key is left intact

- **WHEN** `config/kaine.toml` already sets `[empatheia.qdrant].api_key` to an
  explicit value and a different key is resolvable from the environment or
  `config/secrets.toml`
- **THEN** the loaded cycle config leaves `empatheia.qdrant.api_key` at its
  explicit value, unchanged

#### Scenario: Key absent everywhere yields a clear error, not a silent empty key

- **WHEN** neither `KAINE_QDRANT_API_KEY` nor `config/secrets.toml`
  `[qdrant].api_key` nor a per-consumer key in `config/kaine.toml` provides a
  key, and a qdrant-backed module (Mnemos or Empatheia) is enabled
- **THEN** no empty `api_key` is injected into that consumer's section
- **AND** the module raises its explicit "requires qdrant_api_key" error

#### Scenario: Missing secrets file does not break boot

- **WHEN** `config/secrets.toml` does not exist but `KAINE_QDRANT_API_KEY` is
  set in the environment
- **THEN** the loader resolves the key from the environment without error
- **AND** the loaded cycle config has `mnemos.qdrant.api_key` and
  `empatheia.qdrant.api_key` equal to the environment-variable value

### Requirement: Freeze control attribution
The cycle freeze control SHALL carry a `source` field identifying who froze the
entity — `"operator"` (the default, written by the Nexus freeze endpoint) or
`"spot"` (written by the supervisor during recovery). Reading a control file with
no `source` SHALL default to `"operator"` (backward compatible). The freeze-watch
loop SHALL pause/resume the cycle on the `frozen` flag regardless of source.

#### Scenario: Operator freeze defaults the source
- **WHEN** the operator freezes via the Nexus endpoint
- **THEN** the control records `source = "operator"`

#### Scenario: Legacy control without source reads as operator
- **WHEN** an existing control file without a `source` field is read
- **THEN** the parsed source is `"operator"`

### Requirement: Supervisor lifecycle and escalation exit
When `[spot].enabled` is true the cycle entrypoint SHALL construct a `ForkManager`
and a module-rebuild closure, parse `[spot]`, construct the supervisor, run it as a
task alongside the cycle and freeze-watch tasks, and await it during shutdown. The
entrypoint SHALL clear any stale escalation record at clean boot (next to the
existing freeze clear) and SHALL propagate a non-zero process exit when the
supervisor escalates, so an escalated run does not appear successful.

#### Scenario: Clean boot clears stale escalation
- **WHEN** the cycle entrypoint starts
- **THEN** any prior `escalation.json` is cleared before the cycle runs

#### Scenario: Escalation yields a non-zero exit
- **WHEN** the supervisor escalates during a run
- **THEN** the entrypoint returns a non-zero exit code after shutting down

### Requirement: Operator freeze suspends the experiential loop

The operator SHALL be able to **freeze** a running cognitive cycle: halt the tick
loop so no Syneidesis broadcast, volition, or conscious moment forms while frozen
— the entity's subjective clock stops. Freezing SHALL be a suspension, not a
shutdown: process and in-memory state are retained, no module teardown or state
flush occurs, and resuming continues from exactly where it left off. While
frozen, live perception capture (microphone, camera) SHALL be paused so no new
sensory data accumulates.

Freeze state SHALL be driven by a persisted operator control
(`state/cycle/control.json` — `{frozen, frozen_at, reason}`) carrying only
operational fields, never sensory content. Because a paused tick loop cannot read
its own resume, resume SHALL be driven by a watcher independent of the tick loop,
so a frozen cycle can always be resumed. The cycle's runtime snapshot SHALL
expose whether it is frozen.

#### Scenario: Freezing halts subjective time

- **WHEN** the operator sets the cycle control to frozen
- **THEN** the cycle stops advancing its tick index
- **AND** no workspace broadcast is published
- **AND** live microphone/camera capture is paused

#### Scenario: Resume works from a frozen state

- **WHEN** a frozen cycle's control is set back to not-frozen
- **THEN** the cycle resumes ticking from where it paused
- **AND** no cognitive state was lost across the freeze

#### Scenario: Freeze is not a shutdown

- **WHEN** the cycle is frozen
- **THEN** the cycle process keeps running and modules are not torn down
- **AND** no state-save/shutdown sequence is triggered

#### Scenario: Control carries no sensory content

- **WHEN** the freeze control file or runtime frozen-state is written
- **THEN** it contains only operational fields (frozen flag, timestamp, optional
  operator reason) and no transcribed text, beliefs, memories, or affect reasons

### Requirement: Deterministic cycle mode
The cognitive cycle SHALL provide an opt-in deterministic mode
(`[experiment].deterministic`) in which two runs with the same seed and the same
input sequence produce identical cognitive trajectories: the same selected
coalitions (entry ids, sources, types, salience scores), the same inhibition
decisions, the same volition outputs, and the same logical event timestamps, tick
by tick. The guarantee SHALL NOT extend to wall-clock latency measurements
(`wall_duration_ms`, `slip_ms`), which remain physical measurements and are
excluded from the reproducibility guarantee.

#### Scenario: Two seeded runs produce identical trajectories
- **WHEN** the cycle runs N ticks twice in deterministic mode with the same seed and the same scripted input
- **THEN** the per-tick selected entries, salience scores, inhibited flags, volition decisions, and logical timestamps are identical across the two runs

#### Scenario: Wall-clock latency is not part of the guarantee
- **WHEN** the two deterministic runs are compared
- **THEN** the trajectory identity holds even though `wall_duration_ms`/`slip_ms` may differ between the runs

### Requirement: Event timestamps come from an injectable source
The cycle SHALL stamp published events from a single injectable wall-clock seam
(default real UTC time). In deterministic mode the timestamp SHALL be a logical
clock derived from the tick index and the target tick period, so timestamps are
identical across runs; in normal mode it SHALL use the injected/real wall clock.

#### Scenario: Logical timestamps in deterministic mode
- **WHEN** deterministic mode is on and tick `k` publishes an event
- **THEN** the event's timestamp equals the fixed base epoch plus `k * target_tick_period`, identical across runs

#### Scenario: Real clock in normal mode
- **WHEN** deterministic mode is off
- **THEN** published events are stamped from the injected wall clock (the real UTC clock by default)

### Requirement: Canonical within-tick event ordering
Before scoring and selection, the cycle SHALL order each tick's gathered events by
a total deterministic key (`source`, `type`, `entry_id`) so that selection
tie-breaks do not depend on dispatch incidentals.

#### Scenario: Tie-break is stable regardless of arrival order
- **WHEN** equal-salience events from different sources are gathered in an arbitrary arrival order
- **THEN** the selection tie-break resolves them in the canonical `(source, type, entry_id)` order

