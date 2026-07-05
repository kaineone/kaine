## Context

Nexus is a server-rendered Jinja2 + vanilla-JS app (no build step, no
framework) served on loopback. It exposes conversation (`/`), diagnostics
(`/diagnostics/`), and an optional evaluation tab. Live data already flows via
SSE (`/diagnostics/stream`, `/conversation/stream`) and JSON snapshots
(`/diagnostics/metrics.json`, `/diagnostics/perception.json`,
`/diagnostics/forks.json`, `/diagnostics/evaluation/summary.json`). A
`PrivacyFilter` strips content fields on the diagnostics surface unless
`dev_content_override` is set. Several backend capabilities are reachable only
via API (fork/merge POST routes) or not surfaced at all (cycle rate control via
the `cycle.control` stream). There is no spec for Nexus today; this change
introduces the `nexus-dashboard` capability.

The operating constraint that motivated this: during bring-up the operator had
no in-UI way to see that Speaches/Chatterbox/Ollama/Qdrant were down — they
debugged from logs. The dashboard must surface dependency health first-class.

## Goals / Non-Goals

**Goals:**
- One glance answers "what is running, degraded, or down?" across services and
  modules.
- Live metrics rendered as real graphs, not raw key-value text.
- Controls in the UI for what the backend already supports.
- A professional, cohesive visual design across all surfaces.
- Stay all-local (no CDN/runtime network), loopback-only, privacy-preserving.

**Non-Goals:**
- No SPA framework or npm build step — keep server-rendered + vanilla JS.
- No new persistence layer for metric history; time-series graphs buffer recent
  points client-side from the existing SSE stream.
- No change to the privacy model or to what content is exposed by default.
- Not adding application-level encryption (separate future change).
- Not redesigning the cognitive modules — Nexus is read/observe + the controls
  that already have backend support.

## Decisions

- **Charting: one small, MIT-licensed library vendored locally** (e.g. uPlot,
  ~40 KB, canvas time-series) committed under `kaine/nexus/static/vendor/`, plus
  hand-rolled inline-SVG sparklines/gauges for simple indicators. Rationale:
  "proper dashboard graphs" needs a real time-series renderer, but
  [[feedback_no_cloud_runtime]] forbids a CDN at runtime — so the asset is
  vendored and served from `static/`. Rejected: Chart.js (heavier), D3 (overkill
  + build), CDN includes (violates all-local).
- **Health via a server-side probe endpoint `/diagnostics/health.json`.** It
  checks each dependency with a short per-probe timeout and returns
  `{name, role, status: up|down|degraded|not_configured, detail, checked_at}`:
  Redis (client PING), Qdrant (`/readyz` + api-key), Ollama (`/v1/models`,
  cross-check configured `model_id` present), Speaches (`/v1/models`),
  Chatterbox (`/`), ONA (`NAR` binary present+executable), plus per-module state
  pulled from `runtime.json` + perception state. Results are **cached briefly**
  (a few seconds) so polling the page doesn't hammer services, and probes run
  concurrently with a hard timeout so a hung dependency never blocks the page.
  A dependency is `not_configured` (not `down`) when its module is disabled —
  e.g. Chatterbox shows neutral when `audio_out=false`, not red.
- **Graphs consume existing streams; client buffers a ring of recent points.**
  No server-side history store. The diagnostics JS keeps a bounded in-memory
  buffer per series (cycle Hz, affect VAD, salience) fed by `/diagnostics/stream`
  SSE; evaluation/attribution charts read the batch `summary.json`. Keeps the
  server stateless and avoids a metrics DB.
- **Controls map to existing backends.** Cycle rate → new POST that publishes a
  `cycle.set_rates` event to `cycle.control` (the cycle already honors it).
  Fork/merge → wire the existing POST `/diagnostics/forks` and `/merges` into UI
  forms. Perception toggles → keep. Each control that reaches outward or is hard
  to reverse keeps a confirm dialog (perception already does).
- **`dev_content_override` stays sensitive.** If exposed as a runtime toggle it
  flips the privacy boundary, so it is gated behind an explicit confirm and the
  existing "dev mode" banner; default remains off. Lower priority than the
  health board and may ship as a follow-up.
- **Contract preservation.** All current routes and JSON shapes remain; new
  endpoints are additive. The `PrivacyFilter` and loopback bind are unchanged.
  Existing tests must continue to pass unmodified.

## Risks / Trade-offs

- [Health probes hammer services or hang the page] → concurrent probes, short
  timeouts, short-TTL cache; the page renders the board from cache and refreshes
  async.
- [Vendored chart asset drifts / supply chain] → pin a specific version+hash,
  commit it, document provenance; it is static and served locally only.
- [Runtime `dev_content_override` toggle widens content exposure] → gated by
  confirm + banner, default off, optional/deferred; the privacy filter logic is
  untouched for the default path.
- [Scope creep — this is a large surface] → phase it (see tasks): health board
  first (the operator's stated need), then visual system, then graphs, then
  controls; each phase is independently shippable.

## Migration Plan

Additive and incremental. Existing routes/templates keep working; the redesign
re-skins them and adds endpoints. No data migration. Rollback = revert the
templates/static + new routes. Ship in phases so partial delivery is still an
improvement.

## Open Questions

- Which exact chart lib (uPlot vs. a hand-rolled canvas) — settle during the
  visual-system phase against bundle size and the specific graphs needed.
- Should health-probe results also publish to the bus (for the evaluation
  sidecar) or stay UI-only? Default: UI-only to avoid coupling.
- Is a runtime `dev_content_override` toggle wanted at all, or keep it
  config-only? Defer to operator preference.
