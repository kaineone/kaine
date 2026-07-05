# Make Nexus real-time, responsive, and remote-friendly

## Why

A UI review of `kaine/nexus` found the observability surface is well-built (coherent
hand-rolled LCARS theme, uPlot ring buffers, targeted DOM updates, strong
accessibility scaffolding, and a genuinely sound render-layer privacy boundary), but
its update path has a structural problem that makes a continuously-updating stream
feel laggy, plus several polish and remote-usability gaps. The operator runs this
remotely over Tailscale, so responsiveness on a phone matters.

Root issue (highest leverage): the console opens **eight independent `EventSource`
connections** to the same `/diagnostics/stream` endpoint (enumerated in `nexus.js`
and `nexus_console.js`). Browsers cap ~6 concurrent HTTP/1.1 connections per host,
so 8 SSE plus the polling fetches **saturate the connection pool** — streams stall
and polls queue. Worse, `BusBridge._dispatch` (`bridge.py:130`) privacy-filters and
JSON-encodes every bus event **once per client**, so each event is filtered 8×.

Secondary findings: a health poll interval (2.5s) that undercuts its own 5s cache
(`HealthProber`), doubling real probe traffic; no teardown or `visibilitychange`
pause (a backgrounded phone tab streams forever); no connection-status affordance (a
dropped Tailscale link silently freezes the UI on stale numbers); a 1.3MB
unminified `three.module.js` on first paint; `health.py` as a 1,144-line monolith;
weak mobile behavior (console tuned for a 4K wall with a wheel-to-scroll-sideways
hijack); sub-AA contrast on muted text; and some dead code (`.conversation` CSS,
`ev.signals`/`observations` template branches, a `/diagnostics/embed` doc that
doesn't exist).

## What Changes

**Plan-only. Ships no behavior code.** Phased design-of-record; quick wins first.

**Phase 1 — quick wins (low risk, high perceived quality):**
1. Collapse the 8 `EventSource`s into **one** multiplexed SSE + a tiny client-side
   pub/sub dispatcher; each feature subscribes a callback. Single biggest smoothness
   win.
2. Privacy-filter **once per event** in `BusBridge._dispatch`, then fan the filtered
   event to per-client queues (all clients are the same `diagnostics` surface today).
3. Align the health poll interval to the cache TTL (>= 5s) or drive it from the SSE.
4. Pause SSE + intervals on `document.hidden`; add a visible live/reconnecting
   connection indicator.
5. Contrast pass on muted/dim text to reach WCAG AA; add a mobile breakpoint that
   switches the console to vertical scroll.
6. Minify or lazy-load `three.module.js` (cosmetic presence viz) so the operational
   surface paints first; delete dead `.conversation` CSS and the dead
   `ev.signals`/`observations` template branches; fix or add the `/diagnostics/embed`
   doc.

**Phase 2 — structural:**
7. Decompose `health.py` into `health/{prober,blocks,probes,config}.py`, keeping the
   `HEALTH_BLOCK_KEYS` orphan-guard contract in one home.
8. Server-push metrics/health/pacing/module-activity as periodic SSE events, removing
   the overlapping `NexusVitals`/`NexusMetrics`/`NexusSpot` fetch loops.
9. Refactor the vanilla JS into ES modules with a shared SSE bus and one `fetchJson`;
   extract a shared `_scripts.html` for the duplicated console/diagnostics wiring.
10. Replace `window.location.reload()` after locus/fork/merge with targeted DOM
    updates from the response, matching the existing optimistic-update pattern.
11. Optional console layout toggle (glanceable-horizontal vs. vertical) to de-risk
    the 4K-tuned interaction model on remote/phone clients.

## Impact

- Affected specs: `nexus-observability`, `nexus-dashboard`.
- Affected code (later pass): `kaine/nexus/bridge.py`, `diagnostics.py`, `health.py`,
  `static/nexus.js`, `static/nexus_console.js`, `static/style.css`,
  `templates/console.html` + `diagnostics.html` + `_*` partials, `README.md`.
- No change to the privacy boundary's guarantees; item 2 preserves identical filtered
  output. The single-SSE refactor also reduces server CPU (filter/encode 1× not 8×).
- Coordinate with `remote-perception-bridge` (the Tailscale operator-client change),
  since the mobile/responsive items directly serve that use case.
