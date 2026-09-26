## ADDED Requirements

### Requirement: Plugins may observe cycle ticks
KAINE SHALL call `on_cycle_tick(tick)` once per cycle tick on every loaded plugin that implements it, after the tick's `cycle.tick` event is published, passing a read-only mapping with `tick_index`, `wall_duration_ms`, `target_duration_ms`, `slip_ms`, `is_experiential`, `processing_rate_hz`, `experiential_rate_hz` and `access_drive`. Plugins that do not implement the method SHALL NOT be called, and a run with no such plugins SHALL behave as before.

#### Scenario: Hook receives each tick
- **WHEN** a loaded plugin implements `on_cycle_tick` and the cycle runs three ticks
- **THEN** the hook is called three times with increasing `tick_index` values

#### Scenario: Plugin without the hook
- **WHEN** a loaded plugin does not implement `on_cycle_tick`
- **THEN** the cycle runs without calling it and without error

### Requirement: A failing hook never stops the cycle
An exception raised by `on_cycle_tick` SHALL be logged at WARNING on its first occurrence and every 100th thereafter, naming the plugin, and the cycle SHALL continue with its next tick.

#### Scenario: Hook raises
- **WHEN** `on_cycle_tick` raises on every call for five ticks
- **THEN** the cycle completes all five ticks and exactly one WARNING naming the plugin is logged

### Requirement: The hook is observation only
The mapping passed to `on_cycle_tick` SHALL be a copy, so mutating it SHALL NOT change the published `cycle.tick` payload or the cycle's state, and the hook's return value SHALL be ignored.

#### Scenario: Hook mutates its argument
- **WHEN** the hook sets `tick["experiential_rate_hz"] = 0`
- **THEN** the cycle's effective experiential rate and the published event are unchanged

### Requirement: Cycle observation is recorded
The run manifest's plugin entry SHALL include `observes_cycle`, true when the plugin implements `on_cycle_tick`.

#### Scenario: Manifest entry
- **WHEN** a plugin implementing `on_cycle_tick` is loaded
- **THEN** its manifest entry has `observes_cycle: true`
