## Why

Nexus today is functional but bare: a single-column monospace dark page, data
shown only as `<dl>`/`<table>`/`<ol>`, no charts, and read-only except the
perception toggles. Crucially, **it gives the operator almost no visibility into
what is actually running**. During live bring-up the operator repeatedly could
not tell whether STT (Speaches), TTS (Chatterbox), the LLM (Ollama), Qdrant,
Redis, or a given module was up, down, or degraded — they only found out by
reading server logs. The diagnostics surface should answer "what's running and
what's broken?" at a glance, present live metrics as proper graphs, and expose
the controls the backend already supports (cycle rate, fork/merge, perception,
dev-content) instead of hiding them behind API-only endpoints.

## What Changes

- **Service & dependency health panel** (primary): a live status board on
  `/diagnostics/` showing each external dependency — Ollama/LLM (Lingua,
  Hypnos), Speaches/STT (Audio In), Chatterbox/TTS (Audio Out), Qdrant
  (Mnemos), Redis (bus), ONA `NAR` (Nous) — as up / down / degraded /
  not-configured, plus each enabled module's state (initialized, capturing,
  erroring). Backed by a new lightweight health-probe endpoint.
- **Professional visual design system**: a polished dashboard layout (responsive
  card grid, refined dark theme, typographic hierarchy, status colors,
  iconography) replacing the bare single-column monospace page — applied across
  conversation, diagnostics, and evaluation surfaces.
- **Live metric visualizations**: time-series graphs and indicators for data
  already available — cycle processing/experiential Hz and tick rate, Thymos
  affect (valence/arousal/dominance) over time, salience, Mnemos memory counts,
  module-attribution bar charts, A/B divergence, voice-alignment similarity,
  memory-probe accuracy — using a **locally vendored** charting library (no CDN;
  all-local at runtime).
- **Expanded controls**: surface existing backend capabilities in the UI —
  cycle rate control (via the `cycle.control` stream), fork create + merge
  (API exists, no UI), perception toggles (keep), and a dev-content-override
  toggle. Each outward/irreversible control keeps a confirm step.
- **Preserved contracts**: the privacy boundary (content stripped on
  diagnostics unless `dev_content_override`), loopback-only binding, surface
  enable/disable flags, and all existing route/JSON shapes that current tests
  assert.

## Capabilities

### New Capabilities

- `nexus-dashboard`: the operator-facing dashboard — service/dependency health
  board, professional visual design, live metric visualizations, and the
  controls that drive the running entity, all within the existing privacy and
  loopback constraints.

### Modified Capabilities

<!-- none — Nexus has no prior capability spec; routes/bridge/privacy are
     implementation that this capability now formalizes the UI layer over. -->

## Impact

- **Code**: `kaine/nexus/` — templates (`_base.html`, `diagnostics.html`,
  `conversation.html`, `evaluation.html`), `static/style.css`, `static/nexus.js`;
  a new health-probe module + route (e.g. `/diagnostics/health.json`); a new
  control route for cycle rate; vendored chart asset under `static/`.
- **Config**: possibly a `[nexus]` knob for health-probe interval/timeouts; no
  change to privacy or surface-enable semantics.
- **Dependencies**: one vendored front-end charting asset committed under
  `static/` (no runtime network fetch). No new Python runtime deps required for
  health probes beyond what's already used (httpx/redis/qdrant clients).
- **Tests**: extend `tests/test_nexus_*` for the health endpoint and new
  controls; preserve existing privacy/route assertions
  (`test_nexus_routers`, `test_nexus_privacy`, `systems/test_nexus_subsystem`).
- **Docs**: a short operator note on reading the health board.
