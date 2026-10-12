## MODIFIED Requirements

### Requirement: Phase-3 associative replay with World model scenarios
Sleep phase 3 SHALL replay traces from different memory periods in novel
combinations, cue World model for scenario extensions by publishing to
`phantasia.scenario`, and re-inject the resulting associations into the workspace.
Before `phantasia-dreamerv3` is present, the World model cue SHALL be a no-op stub.
Cross-period selection SHALL draw on the short-term buffer, the traces phase 1
of the same sleep consolidated, and the newest `cross_period_candidates`
points of the persisted episodic collection, read without vectors through the
storage backend's `recent_points()`, on every backend, with each trace counted
once.

#### Scenario: Associative phase cues World model
- **WHEN** phase 3 runs with World model enabled
- **THEN** World model is cued and `phantasia.scenario` events are consumed and
  re-injected into the workspace

#### Scenario: Cross-period traces are combined
- **WHEN** phase 3 selects traces for replay
- **THEN** traces from at least two distinct memory periods appear in the same
  replay batch

#### Scenario: Selection works on a backend without in-process collections
- **WHEN** older traces are persisted in episodic memory on a backend that does
  not expose its points in process, phase 1 has consolidated newer traces, and
  the short-term buffer is empty
- **THEN** cross-period selection returns the consolidated and the older
  traces, each once, across at least two periods

#### Scenario: The episodic read is bounded and vector-free
- **WHEN** `cross_period_candidates` is 1 and the episodic collection holds
  older traces and the newly consolidated ones
- **THEN** only the newest episodic point is read, no vector is read, and the
  older traces are left out
