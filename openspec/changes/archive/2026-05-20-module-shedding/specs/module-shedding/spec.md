## ADDED Requirements

### Requirement: Cycle tolerates arbitrary module subsets
The CognitiveCycle SHALL run without per-tick errors against any
subset of the twelve canonical module names (`echo`, `soma`,
`chronos`, `topos`, `nous`, `mnemos`, `eidolon`, `thymos`, `praxis`,
`lingua`, `audio_out`, `audio_in`, `hypnos`). For each of the
documented combinations — full stack, no-Lingua, no-Topos, cognition-
only, perception-only, lone-Soma, empty — the cycle SHALL tick at
least ten times with `error_counts` remaining empty and the workspace
broadcast SHALL fire on every experiential tick where at least one
event was collected.

#### Scenario: Full stack composes events from every stream
- **WHEN** all twelve module names are registered and each publishes
  one event before a tick
- **THEN** `tick.events_collected >= 12` and the broadcast contains
  events whose `source` set is a subset of the registered names

#### Scenario: Cognition-only still broadcasts
- **WHEN** only `nous`, `mnemos`, and `eidolon` are registered
- **THEN** the cycle ticks ten times with no errors and the broadcast
  selects only events sourced from those three modules

#### Scenario: Empty registry produces empty but error-free broadcasts
- **WHEN** zero modules are registered
- **THEN** the cycle ticks ten times with no errors and each tick's
  `events_collected == 0`

### Requirement: Syneidesis composes only from registered streams
Syneidesis SHALL never include an event in a workspace broadcast
whose `source` is not in the active module registry. When a module is
shed mid-run, subsequent broadcasts SHALL stop including its events
within at most one tick.

#### Scenario: Shed module's events drop out
- **WHEN** a registry contains modules `{"a", "b"}`, both publish an
  event, then `b` is unregistered before the next tick
- **THEN** the next broadcast contains only events sourced from `a`
