## 1. Advisories

- [x] 1.1 `UndefinedRunTracker`, `SilenceTracker` and the advisory constants in `kaine.lifecycle.welfare_signal`
- [x] 1.2 The welfare observer follows `topos.out` and `audition.out` from their tail, ignores reports from before its start, and publishes the blind and silent advisories and their clears content-free, also to its rollup
- [x] 1.3 `[evaluation.welfare].blind_sensor_samples`, default 0 (one distress duration, on the read clock and on the reports' timestamps)
- [x] 1.4 A reset line in the rollup at each observer start
- [x] 1.5 Tracking runs after the stream handler and cannot skip the Interoception distress handling
- [x] 1.6 Tests: the trackers, the observer per processor, the default threshold, lag, backlog and pre-start reports, the reset line, tracking failure, and that the protective monitor neither counts nor acts on any advisory while still acting on gray-zone events

## 2. Surfaces

- [x] 2.1 The curated research log records all four types with exact allowlists
- [x] 2.2 The rollup reader derives each processor's state from its latest advisory after the latest reset with no line window and decrypts encrypted lines; the Dashboard welfare block, the entity-care panel and the evaluation tab's live path show it
- [x] 2.3 Tests: research log allowlists, restart while raised, a long rollup, encrypted lines, panel rendering

## 3. Documentation

- [x] 3.1 Research-data docs (welfare observer), preservation docs, Dashboard docs, architecture, configuration reference
