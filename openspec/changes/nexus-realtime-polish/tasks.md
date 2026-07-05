# Tasks — Nexus real-time + polish

> **Design-of-record only.** Plan, not implement. Phase 1 is independent quick wins;
> Phase 2 is structural and should follow.

## Phase 1 — quick wins
- [ ] 1.1 One multiplexed `EventSource` + client-side pub/sub; delete the 8 separate
      streams (incl. `NexusSSE.subscribeMetrics`'s counter-only stream). Route every
      feature (charts, fatigue, spot, preservation, vitals, reveal, presence) through it.
- [ ] 1.2 Filter once per event in `BusBridge._dispatch`, then fan to queues.
- [ ] 1.3 Set health poll interval >= 5s (cache TTL) or drive from SSE; de-duplicate
      the overlapping metrics/health fetches.
- [ ] 1.4 Pause SSE + intervals on `document.hidden`; add a live/reconnecting indicator.
- [ ] 1.5 Contrast pass on `--fg-dim`/muted text to WCAG AA; add a mobile breakpoint
      (console → vertical scroll; disable the wheel-hijack on small screens).
- [ ] 1.6 Minify/lazy-load `three.module.js`; delete dead `.conversation` CSS + dead
      `ev.signals`/`observations` branches in `_preservation_events.html`; fix the
      `/diagnostics/embed` README drift.

## Phase 2 — structural
- [ ] 2.1 Decompose `health.py` → `health/{prober,blocks,probes,config}.py`; keep the
      `HEALTH_BLOCK_KEYS` orphan-guard contract in one home.
- [ ] 2.2 Server-push metrics/health/pacing/module-activity as periodic SSE events;
      retire the `NexusVitals`/`NexusMetrics`/`NexusSpot` poll loops.
- [ ] 2.3 Refactor JS into ES modules with a shared SSE bus + one `fetchJson`; extract
      `_scripts.html`.
- [ ] 2.4 Replace `window.location.reload()` (locus/fork/merge) with targeted DOM
      updates from the response.
- [ ] 2.5 Optional: console layout toggle (glanceable-horizontal vs. vertical).
- [ ] 2.6 Status chip reflects real cycle state: replace the hardwired
      awake/sleeping binary (which read "awake" with no cycle running) with a
      four-state chip OFFLINE > FROZEN > SLEEPING > AWAKE, computed live from
      `cycle_status` + the freeze flag (metrics push) and Hypnos sleep/wake
      events over the single SSE. Page-load default is OFFLINE. Surface `frozen`
      (metadata-only) in the metrics payload that feeds the chip; add
      offline/frozen badge styles at WCAG AA.

## Verification
- [ ] V.1 Confirm the render-layer privacy boundary is unchanged (no cognitive
      content in any diagnostics template) after the refactor.
- [ ] V.2 Measure: one SSE connection open on the console; event filtered once; first
      paint no longer blocked on the 1.3MB viz.
