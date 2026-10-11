## 1. Implementation

- [x] 1.1 Phase 2 replays before it downscales; voice alignment runs before the affective reset, which ends the sleep
- [x] 1.2 Hypnos opens and closes the Mnemos replay window around phase 2's replay; `hypnos.sleep.started` no longer opens it
- [x] 1.3 Cross-period selection draws on the consolidated batch and on persisted episodic memory through the storage export
- [x] 1.4 Tests: phase order, the window through a real sleep on the bus with an empty buffer, cross-period selection on a backend without in-process collections and on sqlite-vec
- [x] 1.5 Docs: Hypnos, Mnemos and sleep pages
