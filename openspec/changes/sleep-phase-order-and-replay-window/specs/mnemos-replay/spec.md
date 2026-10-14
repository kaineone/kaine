## MODIFIED Requirements

### Requirement: Workspace re-injection during maintenance only
The episodic memory module SHALL publish selected traces as `episodic_memory.replay` events carrying the trace
content for re-processing, and SHALL do so only during an active sleep module's replay
window. The sleep module SHALL open the window through the episodic memory module's `open_replay_window()`
inside a sleep, immediately before phase 2 calls `replay_now()`, and SHALL
close it through `close_replay_window()` once replay returns or raises.
`sleep.sleep.started` on the bus SHALL NOT open the window, and
`sleep.sleep.completed` SHALL close it. If `replay()` is called outside an open
window, it SHALL refuse to emit events and SHALL raise a precondition error
rather than publishing silently.

#### Scenario: Replay emits trace content in a window
- **WHEN** `replay()` runs inside an active sleep module's maintenance replay window
- **THEN** `episodic_memory.replay` events are published containing the selected traces'
  content

#### Scenario: No replay while awake — guard fires
- **WHEN** `replay()` is called while the system is in normal waking operation
  (no active sleep module's replay window)
- **THEN** no `episodic_memory.replay` event is published and a precondition error is
  raised

#### Scenario: A quick phase 1 does not fail phase 2
- **WHEN** a real sleep module and a real episodic memory module share a bus, the episodic memory module's peer poll is
  running, the short-term buffer is empty, and `enter_sleep()` runs
- **THEN** phase 2 succeeds, the sleep summary is not an alert, and after the
  sleep `replay_now()` raises the window error

#### Scenario: Sleep start on the bus does not open the window
- **WHEN** the episodic memory module handles `sleep.sleep.started`
- **THEN** the replay window stays closed
