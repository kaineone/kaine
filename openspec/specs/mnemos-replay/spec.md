# mnemos-replay Specification

## Purpose
This capability extends the episodic memory module so stored memory traces are tagged with the latest affect state, and recall selects traces by affect intensity and recency for re-injection into the workspace during maintenance windows only. It also lets logs redact sensitive memory content.

## Requirements

### Requirement: Affect-tagging on store
The episodic memory module SHALL subscribe to `affect.state`, cache the latest affect, and tag each
newly stored memory trace with that affect (intensity and VAD), so that recall
can bias by affect intensity.

#### Scenario: Stored trace carries current affect
- **WHEN** a memory is stored after a `affect.state` event has been observed
- **THEN** the stored trace's affect tag reflects that state's intensity and VAD

### Requirement: Affect/recency replay selection
The episodic memory module SHALL select replay traces by a score combining affect intensity and
recency (`affect_weight × intensity + recency_weight × recency`), returning the
top `selection_top_k` traces. The candidates SHALL be every persisted trace
stored since the previous downscaling (`born_sleep` equal to the sleep count),
including those persisted by eviction during the wake, plus any short-term
entry. Recency SHALL map each candidate's `entity_time` linearly onto [0, 1]
across the candidates. Each replayed trace SHALL name its point id and its
collection.

#### Scenario: Emotionally significant, recent traces rank first
- **WHEN** the replay selector ranks a set of traces
- **THEN** a high-intensity recent trace ranks above a low-intensity old one

#### Scenario: An evicted trace of the wake can be replayed
- **WHEN** a high-arousal trace stored early in a wake was persisted by eviction
  before the sleep
- **THEN** the sleep's replay selects it

#### Scenario: Earlier wakes are not in the pool
- **WHEN** a sleep replays
- **THEN** no trace stored before the previous sleep is a candidate

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

### Requirement: Redact-content option for logs
The episodic memory module SHALL support a `redact_content` option (default on) for `episodic_memory.replay`
events destined for logs and sidecar observers. When enabled, the replay observer
sidecar SHALL receive only memory IDs, not the textual content of replayed traces,
preserving the privacy of memory content in operational logs.

#### Scenario: Redacted replay carries IDs only
- **WHEN** `redact_content` is true and a replay observer receives a `episodic_memory.replay`
  event
- **THEN** the observer payload contains memory IDs and metadata but no raw
  trace text content

#### Scenario: Unredacted replay carries full content
- **WHEN** `redact_content` is false and a replay observer receives a `episodic_memory.replay`
  event
- **THEN** the observer payload contains the full trace text content

### Requirement: Replay draws on the sleep's consolidated traces
When sleep phase 1 moves the short-term buffer into the episodic store,
The episodic memory module SHALL keep the moved traces, each with the episodic point id it was
stored under, and phase 2's replay SHALL include them among its candidates,
alongside any trace still in the short-term buffer. Each consolidation pass
SHALL replace the kept traces, and the episodic memory module SHALL drop them when the sleep
completes, so a sleep replays only traces consolidated in that sleep or still
held short-term.

#### Scenario: Phase 2 replays what phase 1 consolidated
- **WHEN** the short-term buffer holds three traces, the replay window is open,
  and phase 1 then phase 2 run
- **THEN** phase 1 moves three traces, phase 2 publishes a `episodic_memory.replay`
  event for each, and each event's `memory_id` is the trace's episodic point id

#### Scenario: A later sleep does not replay an earlier sleep's traces
- **WHEN** a consolidation pass has moved traces, and a later pass runs with an
  empty short-term buffer
- **THEN** a replay after the later pass finds no candidates and publishes
  nothing

### Requirement: A stored broadcast records a replay by id only
When a `episodic_memory.replay` event is a member of a broadcast that the episodic memory module stores,
the stored text SHALL record the event and the replayed trace's `memory_id`
and SHALL NOT include the replayed trace's text.

#### Scenario: Replay text is not nested into a new trace
- **WHEN** a broadcast containing a `episodic_memory.replay` event with `memory_id`
  `abc123` is serialized for storage
- **THEN** the text contains `episodic_memory:episodic_memory.replay=<replay of abc123>` and none
  of the replayed trace's text
