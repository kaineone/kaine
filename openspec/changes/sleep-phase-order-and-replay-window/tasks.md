## 1. Implementation

- [x] 1.1 Phase 2 replays before it downscales; voice alignment runs before the affective reset, which ends the sleep
- [x] 1.2 Sleep opens and closes the Episodic memory replay window around phase 2's replay; `hypnos.sleep.started` no longer opens it
- [x] 1.3 Cross-period selection draws on the consolidated batch and on persisted episodic memory through the storage export
- [x] 1.4 Tests: phase order, the window through a real sleep on the bus with an empty buffer, cross-period selection on a backend without in-process collections and on sqlite-vec
- [x] 1.5 Docs: Sleep, Episodic memory and sleep pages
- [x] 1.6 Review fixes: the affective reset runs in a `finally`, shielded from a second cancel; an aborted completion is published on a cancel
- [x] 1.7 Review fixes: cross-period selection reads the newest `cross_period_candidates` episodic points without vectors through `recent_points()` on every backend
