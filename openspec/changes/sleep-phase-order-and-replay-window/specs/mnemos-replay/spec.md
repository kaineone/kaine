## MODIFIED Requirements

### Requirement: Workspace re-injection during maintenance only
Mnemos SHALL publish selected traces as `mnemos.replay` events carrying the trace
content for re-processing, and SHALL do so only during an active Hypnos replay
window. Hypnos SHALL open the window through Mnemos's `open_replay_window()`
inside a sleep, immediately before phase 2 calls `replay_now()`, and SHALL
close it through `close_replay_window()` once replay returns or raises.
`hypnos.sleep.started` on the bus SHALL NOT open the window, and
`hypnos.sleep.completed` SHALL close it. If `replay()` is called outside an open
window, it SHALL refuse to emit events and SHALL raise a precondition error
rather than publishing silently.

#### Scenario: Replay emits trace content in a window
- **WHEN** `replay()` runs inside an active Hypnos maintenance replay window
- **THEN** `mnemos.replay` events are published containing the selected traces'
  content

#### Scenario: No replay while awake — guard fires
- **WHEN** `replay()` is called while the system is in normal waking operation
  (no active Hypnos replay window)
- **THEN** no `mnemos.replay` event is published and a precondition error is
  raised

#### Scenario: A quick phase 1 does not fail phase 2
- **WHEN** a real Hypnos and a real Mnemos share a bus, Mnemos's peer poll is
  running, the short-term buffer is empty, and `enter_sleep()` runs
- **THEN** phase 2 succeeds, the sleep summary is not an alert, and after the
  sleep `replay_now()` raises the window error

#### Scenario: Sleep start on the bus does not open the window
- **WHEN** Mnemos handles `hypnos.sleep.started`
- **THEN** the replay window stays closed
