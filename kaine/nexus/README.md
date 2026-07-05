# Nexus dashboard — operator notes

Nexus is the loopback-only operator dashboard (`python -m kaine.nexus`). It is
server-rendered (Jinja2 + vanilla JS, no build step) and all assets are served
locally — there is no CDN or runtime network fetch.

The look is an LCARS-inspired evocation (not a clone): a near-black field, slate
panels, red reserved for attention/alerts, blue-grey chrome everywhere else.

## Surfaces

- **console** (`/`) — the single glanceable operator screen. It leads with the
  **Presence** visualizer (see below) and carries the diagnostic/evaluation
  **sections** as collapsible panels: most sit closed and are summoned from the
  left-rail buttons (a section slides in from its button and expands), and a
  situational section (welfare, divergence) **auto-surfaces and flashes** when a
  relevant event arrives. **Health & services** is a compact, scroll-free right
  sidebar (hover a row for detail). The screen never scrolls; a section too long
  for its column continues into the next with a "continued" marker, and extra
  open sections scroll horizontally. **No message content is shown here** —
  only status, metrics, and derived affect.
- **diagnostics** (`/diagnostics/`) — the deep technical view (cycle charts,
  metrics, run identity, controls), reachable from the left-rail "Diagnostics"
  link on every page. Content fields are **stripped** unless
  `dev_content_override` is set in `[nexus]`; status/metric data is always shown
  (it is non-content).
- **evaluation** (`/diagnostics/evaluation/`) — the architecture-thesis
  instrumentation, laid out as a **living research report** (section claims +
  live figures). Scrubbed thesis metrics only, no message text.

## Presence visualizer

The console leads with a "ferrofluid" affect visualizer (Three.js, vendored
under `static/vendor/`). It renders a calm idle state with no entity running and
shifts its mood from live **derived** affect — `thymos.state` `{valence,
arousal}` riding the diagnostics SSE stream — when a cycle is up. It never
receives raw audio or content; the idle look is the honest no-entity state.

## Reading the health board

The **service & dependency health** panel answers "what's running, degraded,
down, or not configured?" without reading logs — compact in the console's right
sidebar (hover for detail) and inline on the standalone diagnostics page. Each
external dependency shows a status chip:

| Status           | Meaning                                                                 |
|------------------|-------------------------------------------------------------------------|
| `up`             | Probe succeeded — the service is reachable and (for the LLM) the configured `model_id` is served. |
| `degraded`       | Reachable but not fully healthy — e.g. HTTP non-200, or the LLM is up but the configured model is not in `/v1/models`. |
| `down`           | Unreachable, refused, errored, or the probe exceeded its timeout (~2s). |
| `not configured` | The owning module is **disabled** in `[modules]`. Neutral, not an error — e.g. Chatterbox shows neutral when `vox = false`. |

Dependencies covered: **Redis** (bus, PING), **Qdrant** (Mnemos, `/readyz` with
api-key), **Chat LLM** (Lingua/Hypnos, `/v1/models` + model check),
**Speaches** (Audio In STT, `/v1/models`), **Chatterbox** (Audio Out TTS),
**pymdp + JAX** (Nous active inference, import check).

Probes run concurrently with a bounded per-probe timeout and are cached for a
few seconds, so opening or polling the page never hangs on a stuck dependency
and never floods a service with checks. A hung dependency renders `down` after
the timeout while every other row still renders.

Below the dependencies, the **modules** grid shows each module's live state:
`disabled` (config off), `idle` (enabled but not in the running cycle),
`running` (enabled and present in the cycle), or `🔴 capturing` (a perception
sensor is live). Module state is read from `state/cycle/runtime.json` and
`state/perception/runtime.json`.

## Live charts

Cycle processing/experiential rate, Thymos affect (valence/arousal/dominance),
and salience render as live time-series fed by the diagnostics SSE stream
(`/diagnostics/stream`), buffered client-side. Evaluation charts read the batch
`summary.json`. Panels show an empty placeholder when a source has no data yet.
The chart library (uPlot) is vendored under `static/vendor/` — see its README.

## Controls

- **Perception toggles** — start/stop the live microphone/camera. Turning a
  sensor **on** requires a confirm.
- **Cycle rate** — publishes `cycle.set_rates` to the `cycle.control` stream;
  the running cycle applies it. Changing pacing requires a confirm.
- **Fork / merge** — create a fork from a snapshot, or merge two snapshots, via
  the existing endpoints. Both require a confirm.

Controls only appear when their backend is wired (e.g. the rate control needs a
publisher and the cycle to be running).
