# Tasks — Enforce both admissibility checks in export

> **Design-of-record only.** Plan, not implement. Do not start without a go.

## 1 — Range sweep in the export path
- [x] 1.1 `build_research_bundle` calls `sweep_run` alongside `scan_run`.
- [x] 1.2 Record both verdicts (completeness + range) in the bundle manifest.

## 2 — Default require_admissible = True
- [x] 2.1 Flip the default so an inadmissible run is blocked from the default export.
- [x] 2.2 Keep an explicit operator override; when used, stamp the manifest with an
      `admissibility_override` marker + reason.
- [x] 2.3 Update `config/kaine.toml` + docs for the new default.

## 3 — Restart / multi-process detection
- [x] 3.1 Detect a `seq` reset or `run_id` change within a logical run; the
      admissibility report flags "restart/multi-process detected" instead of clean.
- [x] 3.2 Decide (design) whether restart runs are inadmissible by default or merely
      flagged — recommend inadmissible-by-default for the reproducible research path.

## 4 — Tests
- [x] 4.1 A run with an out-of-range value is blocked by the default export path.
- [x] 4.2 An incomplete run (missing stream / seq gap) is blocked.
- [x] 4.3 A simulated mid-run restart is flagged, not reported clean.
- [x] 4.4 The explicit override exports and is recorded in the manifest.
