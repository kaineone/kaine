## 1. Dwell in the hearing block

- [x] 1.1 `read_hearing_stage` reads the dwell from the owner file, same-stage only; bounds from the runtime entry
- [x] 1.2 The cycle's runtime entry carries the bounds (`runtime_reading`, `HearingStageState.params`)

## 2. Panel

- [x] 2.1 Formatter appends "H h of MIN to MAX h"; none when missing or at stage 4

## 3. Tests and docs

- [x] 3.1 Python tests: owner file round trip, wrong stage, missing and unusable files, route, runtime reading
- [x] 3.2 JS tests: dwell shown, missing dwell, missing bounds, stage 4
- [x] 3.3 `docs/05-dashboard.md` and `docs/06-operation/development.md`
