## 1. Declarations
- [x] 1.1 `BaseModule.relieves_drives` (empty default) and per-module tags reproducing the previous table.
- [x] 1.2 `kaine/workspace/strategies.py`: `DRIVES`, `SCAFFOLDING_DRIVE_SOURCES`, `build_drive_sources(tags_by_source)`; `DriveRelevanceGoalScorer(drive_getter, *, drive_sources, attenuation)`.

## 2. Wiring
- [x] 2.1 `make_salience_factors(..., drive_sources=...)`; the cycle entry point passes the registry-derived mapping.

## 3. Tests
- [x] 3.1 The union of module tags plus scaffolding equals the previous table.
- [x] 3.2 Every tag is a Thymos drive; the existing scorer tests pass with an explicit mapping.
