## ADDED Requirements

### Requirement: Affect-tagging on store
Mnemos SHALL subscribe to `thymos.state`, cache the latest affect, and tag each
newly stored memory trace with that affect (intensity and VAD), so that recall
can bias by affect intensity.

#### Scenario: Stored trace carries current affect
- **WHEN** a memory is stored after a `thymos.state` event has been observed
- **THEN** the stored trace's affect tag reflects that state's intensity and VAD

### Requirement: Affect/recency replay selection
Mnemos SHALL select replay traces by a score combining affect intensity and
recency (`affect_weight × intensity + recency_weight × recency`), returning the
top `selection_top_k` traces.

#### Scenario: Emotionally significant, recent traces rank first
- **WHEN** the replay selector ranks a set of traces
- **THEN** a high-intensity recent trace ranks above a low-intensity old one

### Requirement: Workspace re-injection during maintenance only
Mnemos SHALL publish selected traces as `mnemos.replay` events carrying the trace
content for re-processing, and SHALL do so only during an active Hypnos replay
window. If `replay()` is called outside such a window, it SHALL refuse to emit
events and SHALL raise a precondition error (or equivalent guard) rather than
publishing silently.

#### Scenario: Replay emits trace content in a window
- **WHEN** `replay()` runs inside an active Hypnos maintenance replay window
- **THEN** `mnemos.replay` events are published containing the selected traces'
  content

#### Scenario: No replay while awake — guard fires
- **WHEN** `replay()` is called while the system is in normal waking operation
  (no active Hypnos replay window)
- **THEN** no `mnemos.replay` event is published and a precondition error is
  raised (or the call is otherwise refused with a logged warning)

### Requirement: Redact-content option for logs
Mnemos SHALL support a `redact_content` option (default on) for `mnemos.replay`
events destined for logs and sidecar observers. When enabled, the replay observer
sidecar SHALL receive only memory IDs, not the textual content of replayed traces,
preserving the privacy of memory content in operational logs.

#### Scenario: Redacted replay carries IDs only
- **WHEN** `redact_content` is true and a replay observer receives a `mnemos.replay`
  event
- **THEN** the observer payload contains memory IDs and metadata but no raw
  trace text content

#### Scenario: Unredacted replay carries full content
- **WHEN** `redact_content` is false and a replay observer receives a `mnemos.replay`
  event
- **THEN** the observer payload contains the full trace text content
