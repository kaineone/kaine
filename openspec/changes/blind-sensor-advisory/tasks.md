## 1. Advisory

- [x] 1.1 `UndefinedRunTracker` and the blind-sensor constants in `kaine.lifecycle.welfare_signal`
- [x] 1.2 The welfare observer follows `topos.out` and `audition.out`, publishes `welfare.blind_sensor` and `welfare.blind_sensor_cleared` content-free, and writes both to its rollup
- [x] 1.3 `[evaluation.welfare].blind_sensor_samples`, default 0 (one distress duration)
- [x] 1.4 Tests: the tracker, the observer per processor, the default threshold, and that the protective monitor neither counts nor acts on the advisories while still acting on gray-zone events

## 2. Surfaces

- [x] 2.1 The curated research log records both types with an exact allowlist
- [x] 2.2 The welfare rollup reader, the Nexus welfare block and the entity-care panel show advisories raised and processors blind now; the evaluation tab's live path reports them
- [x] 2.3 Tests: research log allowlist, rollup reader and panel rendering

## 3. Documentation

- [x] 3.1 Research-data docs (welfare observer and event streams), preservation docs, Nexus docs, configuration reference
