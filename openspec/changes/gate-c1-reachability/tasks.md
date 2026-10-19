## 1. Implementation

- [x] 1.1 `hrv_variability_floor` 0.02 in the gate default and the shipped config, with the Moraes et al. 2012 grounding
- [x] 1.2 A withdrawal waits `entrainment_window_seconds` since boot or the last thaw
- [x] 1.3 `development_progress.json` records and restores the jitter counters and the latest entrainment and self-sustain markers, restored before the first probes are scheduled; older files migrate
- [x] 1.4 Tests: the wait after boot and thaw, the counters and markers survive a restart, a restart neither resets nor repeats a pass run, migration of an older file, the floor
- [x] 1.5 Docs: development operation page, configuration reference, glossary
