# Tasks — Nexus real-time + polish

> **Status.** The Phase 1 quick wins and most of Phase 2 shipped with the initial
> public release; this change now reconciles the task list with that shipped, tested
> code and adds a regression guard for the single-`EventSource` invariant (1.1 / V.2).
> Two items remain deferred as later-phase structural/optional work: **2.3** (ES-module
> conversion + `_scripts.html` extraction) and **2.5** (optional layout toggle).

## Phase 1 — quick wins
- [x] 1.1 One multiplexed `EventSource` + client-side pub/sub; delete the 8 separate
      streams (incl. `NexusSSE.subscribeMetrics`'s counter-only stream). Route every
      feature (charts, fatigue, spot, preservation, vitals, reveal, presence) through it.
      `NexusStream` (nexus.js) owns the sole `new EventSource` and fans out via
      `subscribe()`; the counter-only metrics stream delegates to it. Regression-guarded
      by `test_single_multiplexed_eventsource_across_the_bundle`.
- [x] 1.2 Filter once per event in `BusBridge._dispatch`, then fan to queues.
      `bridge.py::_dispatch` filters once then pushes the shared filtered `Event` to
      every client queue; guarded by
      `test_dispatch_calls_privacy_filter_once_per_event_not_once_per_client` +
      `test_dispatch_output_identical_across_all_clients_and_matches_direct_filter`.
- [x] 1.3 Set health poll interval >= 5s (cache TTL) or drive from SSE; de-duplicate
      the overlapping metrics/health fetches. `DEFAULT_CACHE_TTL_S = 5.0` and the vitals
      refresh runs at 5000ms via `NexusVisibility.pausable`; server-push snapshots retire
      the duplicate loops.
- [x] 1.4 Pause SSE + intervals on `document.hidden`; add a live/reconnecting indicator.
      `NexusStream` + `NexusVisibility` pause on `visibilitychange`; `NexusConn` renders
      live/reconnecting/paused state.
- [x] 1.5 Contrast pass on `--fg-dim`/muted text to WCAG AA; add a mobile breakpoint
      (console → vertical scroll; disable the wheel-hijack on small screens).
      `style.css` mobile breakpoints at 640/720/1024px; wheel-hijack short-circuits below
      640px (`initWheelScroll`, nexus_console.js).
- [x] 1.6 Minify/lazy-load `three.module.js`; delete dead `.conversation` CSS + dead
      `ev.signals`/`observations` branches in `_preservation_events.html`; fix the
      `/diagnostics/embed` README drift. Presence viz import is deferred to
      `requestIdleCallback`; dead CSS/branches and the `/diagnostics/embed` doc are gone.

## Phase 2 — structural
- [x] 2.1 Decompose `health.py` → `health/{prober,blocks,probes,config}.py`; keep the
      `HEALTH_BLOCK_KEYS` orphan-guard contract in one home. `health/` is a package;
      `HEALTH_BLOCK_KEYS` is re-exported from `health/__init__.py`.
- [x] 2.2 Server-push metrics/health/pacing/module-activity as periodic SSE events;
      retire the `NexusVitals`/`NexusMetrics`/`NexusSpot` poll loops.
      `diagnostics.py::push_snapshots_periodically` + `BusBridge.publish_synthetic`
      push a combined snapshot over the single stream.
- [ ] 2.3 Refactor JS into ES modules with a shared SSE bus + one `fetchJson`; extract
      `_scripts.html`.
      DEFERRED (later-phase structural). The shared SSE bus (`NexusStream`) and a
      `fetchJson` helper already exist, but the browser-only ES-module conversion and the
      `_scripts.html` extraction of the console/diagnostics wiring are not done. This is a
      large refactor with no server-test surface (browser-only) and real regression risk;
      it is intentionally left for a follow-on per the proposal ("Phase 2 is structural
      and should follow"). Not implemented in this change.
- [x] 2.4 Replace `window.location.reload()` (locus/fork/merge) with targeted DOM
      updates from the response. No `location.reload()` remains in the static JS; updates
      apply in place via the optimistic-update pattern.
- [ ] 2.5 Optional: console layout toggle (glanceable-horizontal vs. vertical).
      DEFERRED (explicitly optional). The responsive breakpoint already switches to a
      vertical layout on small screens; the discretionary user-facing layout toggle is
      not implemented. Not implemented in this change.
- [x] 2.6 Status chip reflects real cycle state: replace the hardwired
      awake/sleeping binary (which read "awake" with no cycle running) with a
      four-state chip OFFLINE > FROZEN > SLEEPING > AWAKE, computed live from
      `cycle_status` + the freeze flag (metrics push) and Hypnos sleep/wake
      events over the single SSE. Page-load default is OFFLINE. Surface `frozen`
      (metadata-only) in the metrics payload that feeds the chip; add
      offline/frozen badge styles at WCAG AA. Chip default is `offline`; `computeChipState`
      follows the OFFLINE > FROZEN > SLEEPING > AWAKE ladder; metrics payload carries the
      `frozen` metadata flag. Guarded by `test_console_status_chip_defaults_to_offline`,
      `test_status_chip_priority_logic_in_js`, `test_metrics_snapshot_carries_frozen_flag_for_status_chip`.

## Verification
- [x] V.1 Confirm the render-layer privacy boundary is unchanged (no cognitive
      content in any diagnostics template) after the refactor. Guarded by the privacy
      suite + `test_console_does_not_render_transcript_text` /
      `test_diagnostics_route_has_no_message_text`; the snapshot-push and status-chip
      inputs are metadata-only.
- [x] V.2 Measure: one SSE connection open on the console; event filtered once; first
      paint no longer blocked on the 1.3MB viz. Exactly one `new EventSource` in the
      bundle (`test_single_multiplexed_eventsource_across_the_bundle`); filter-once
      guarded by the bridge dispatch tests; the presence viz import is lazy
      (`requestIdleCallback`) so first paint is not blocked.
