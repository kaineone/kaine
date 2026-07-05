## 1. Service & dependency health board (the operator's stated need — ship first)

- [x] 1.1 Add a health-probe module under `kaine/nexus/` that checks each
      dependency concurrently with a bounded per-probe timeout: Redis (client
      PING), Qdrant (`/readyz` + api-key), chat LLM (`/v1/models`, verify
      configured `model_id` present), Speaches (`/v1/models`), Chatterbox (`/`),
      ONA `NAR` (binary present + executable). Return
      `{name, role, status, detail, checked_at}` per dependency.
- [x] 1.2 Map module enablement → dependency status: a disabled module's
      dependency is `not_configured`, not `down`. Pull per-module state from
      `runtime.json` + perception state.
- [x] 1.3 Cache probe results with a short TTL; never let a probe block the
      page; expose `GET /diagnostics/health.json`.
- [x] 1.4 Render the health board panel on `/diagnostics/` (status chips,
      color-coded, with detail + last-checked).
- [x] 1.5 Tests: health endpoint shape; disabled-module → not_configured;
      down service → down; timeout → degraded/down without blocking.

## 2. Visual design system

- [x] 2.1 Rework `static/style.css` into a design system: responsive panel/card
      grid, refined dark theme, type scale, status color palette, components
      (chips, cards, tables, buttons). Keep server-rendered + vanilla JS.
- [x] 2.2 Restructure `_base.html` and the three page templates to the panel
      layout WITHOUT dropping any currently-shown data.
- [x] 2.3 Confirm existing route/render tests still pass unmodified; add a smoke
      test that each page renders with the shared layout markers.

## 3. Live metric visualizations

- [x] 3.1 Vendor a small MIT-licensed time-series chart asset under
      `static/vendor/` (pin version + record provenance/hash); no CDN.
- [x] 3.2 In `nexus.js`, buffer recent points per series from the diagnostics
      SSE stream (cycle rate, Thymos affect) and render live time-series.
- [x] 3.3 Render attribution / evaluation summaries as charts from
      `evaluation/summary.json`; empty/placeholder state when data is absent.
- [x] 3.4 Tests: charts render with data, degrade gracefully without it, and no
      runtime network fetch occurs.

## 4. Operator controls

- [x] 4.1 Add a control route that publishes `cycle.set_rates` to the
      `cycle.control` stream; wire a rate control on `/diagnostics/`.
- [x] 4.2 Surface fork-create and snapshot-merge forms backed by the existing
      `POST /diagnostics/forks` and `/merges` endpoints.
- [x] 4.3 Keep perception toggles; ensure every sensor-on / pacing / hard-to-
      reverse control requires an explicit confirm.
- [x] 4.4 Tests: rate control publishes the right event; confirm-gating present;
      fork/merge forms hit the existing endpoints.

## 5. Preserve privacy & loopback

- [x] 5.1 Verify `PrivacyFilter` behavior is unchanged: diagnostics strips
      content unless `dev_content_override`; conversation full; evaluation
      scrubbed; health/metric data shown regardless.
- [x] 5.2 Verify loopback-only bind unchanged.
- [x] 5.3 Run the full nexus test suite (`test_nexus_*`,
      `test_evaluation_nexus_tab`, `systems/test_nexus_subsystem`) green.

## 6. Docs

- [x] 6.1 Short operator note: how to read the health board and what each status
      means.
