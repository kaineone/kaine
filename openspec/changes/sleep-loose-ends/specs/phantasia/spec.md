## MODIFIED Requirements

### Requirement: Offline imagined-scenario generation and workspace re-injection
Phantasia SHALL, on a `mnemos.replay` cue received during offline maintenance,
roll out imagined trajectories from that seed up to `rollout_horizon` and publish
them as `phantasia.scenario` events. `phantasia.scenario` events SHALL be
re-injected into the workspace broadcast during maintenance so that Nous, Thymos,
and Eidolon process them via `on_workspace` (associative consolidation, paper
§3.3.5 phase 3). Hypnos SHALL open Phantasia's scenario window through
`open_scenario_window()` and close it through `close_scenario_window()`.
`hypnos.sleep.started` on the bus SHALL NOT open the window; it SHALL pause the
waking path until `hypnos.sleep.completed`, which SHALL also close the window.
Phantasia SHALL answer a replay cue whose timestamp lies inside the open window
or inside one of the last four closed windows, whenever the cue is handled, and
SHALL ignore any other cue, including a cue from an earlier sleep handled while a
later window is open. `initialize()` SHALL clear the sleep state and close the
window, so a light restart that misses `hypnos.sleep.completed` cannot leave the
waking path paused.

#### Scenario: Replay cue produces a scenario
- **WHEN** Phantasia receives a `mnemos.replay` cue during maintenance
- **THEN** it publishes at least one `phantasia.scenario` event

#### Scenario: Scenario is re-injected into workspace broadcast
- **WHEN** a `phantasia.scenario` event is published during maintenance
- **THEN** the scenario is re-injected into the workspace broadcast so
  Nous, Thymos, and Eidolon process it via on_workspace

#### Scenario: Sleep start on the bus does not open the window
- **WHEN** Phantasia handles `hypnos.sleep.started`
- **THEN** the scenario window stays closed and the waking path pauses

#### Scenario: A cue published inside the window is answered late
- **WHEN** a replay cue published while the window was open is handled after
  Hypnos has closed the window
- **THEN** Phantasia publishes a `phantasia.scenario` seeded from that cue

#### Scenario: A cue published outside the window is ignored
- **WHEN** a replay cue published after the window closed is handled
- **THEN** no `phantasia.scenario` event is published

#### Scenario: A stale cue is ignored while a later window is open
- **WHEN** a replay cue stamped before the open window started is handled
- **THEN** no `phantasia.scenario` event is published

#### Scenario: A late cue from back-to-back sleeps is answered
- **WHEN** a cue stamped inside a closed window is handled while the next
  window is open
- **THEN** Phantasia publishes a `phantasia.scenario` seeded from that cue

#### Scenario: A light restart clears the sleep state
- **WHEN** Phantasia restarts after `hypnos.sleep.started` with its window open
- **THEN** the window is closed and the waking path publishes again
