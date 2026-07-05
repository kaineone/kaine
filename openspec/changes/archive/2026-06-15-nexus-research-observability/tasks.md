# Tasks

## A — Surface the new research/safety systems

- [x] A1. Run identity: add `run_id`, `seed`, `git_sha`, `kaine_version`,
  `deterministic` to `_write_runtime_state` (read via `get_run_context()`);
  surface in `metrics_snapshot`; render a "run identity" block on diagnostics.
- [x] A2. Supervision mode + safety-net gate: write `supervision_mode` and (in
  research mode) the gate `checks` dict to runtime.json; render a prominent
  badge at the top of diagnostics.
- [x] A3. Preservation / welfare-protective events: `nexus.js` handler +
  persistent panel; `HealthProber._preservation_block()` reads
  `state/cycle/preservation/`; `_preservation_events.html` partial; sessionStorage
  persistence; `failed` in `--down` colour.
- [x] A4. Welfare status on diagnostics: compact numeric counter row on the
  entity-care panel via a shared `_welfare_counts` helper.
- [x] A5. Admissibility (lightweight live): `HealthProber._admissibility_block()`
  reports manifest present + last tick index + recording/gap-detected/unknown pill.
- [x] A6. Deterministic-mode indicator: `--degraded` badge near the cycle charts,
  shown only when true.

## B — Polish

- [x] B1. diagnostics: clear "Cycle not running" hint; gate chart/metric sections.
- [x] B2. Freeze toggle: in-place DOM update instead of `location.reload()`.
- [x] B3. Perception toggle: optimistic update + poll `/diagnostics/perception.json`.
- [x] B4. Nav active-page indicator (`_base.html` + `.nav a.active`).
- [x] B5. entity-care: render non-content divergence signals below the summary.
- [x] B6. Spot console empty state: explicit "no incident events" placeholder line.
- [x] B7. health board `checked_at`: human-relative "Xs ago" (keep raw in `data-at`).
- [x] B8. fork table: safe `is mapping` + `["key"] is defined` access.
- [x] B9. cycle-control microcopy: standardize "cycle control" wording.
- [x] B10. research panel: remove the dead `/docs/research-participation.md` link.
- [x] B11. conversation page: empty-history placeholder.
- [x] B12. freeze banner: link "the diagnostics page" to `/diagnostics/`.
- [x] B13. adapters table: empty state "No adapters trained.".
- [x] B14. metrics panel: in-place refresh via `/diagnostics/metrics.json`.

## Tests + validate

- [x] runtime.json carries the new fields; metrics_snapshot surfaces them.
- [x] new health blocks return the right shape.
- [x] privacy: assert NO content field leaks into any new surface.
- [x] templates render.
- [x] `openspec validate nexus-research-observability --strict`.
