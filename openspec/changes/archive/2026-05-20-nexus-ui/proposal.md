## Why

Paper §3.5 and build prompt §8 require Nexus, KAINE's operator UI.
Three distinct surfaces:
- **Conversation view** (§8.1) — read-only stream of external speech
  with entity name from Eidolon and a sleep-status badge from
  Hypnos. Operators see what KAINE says, never how it's computed.
- **Diagnostics dashboard** (§8.2) — module status, latency,
  throughput, temperatures, event rates, fork/merge controls,
  adapter rollback. NO content (no message bodies, no beliefs, no
  memories, no internal speech, no affect reasons).
- **Privacy boundary** (§8.3) — content NEVER leaks into diagnostics;
  diagnostics NEVER shows raw event payloads. A dev-mode override
  exists behind a config flag defaulting to off.

This phase ships all three together. Splitting them led to
recurring churn in earlier prototypes because the conversation and
diagnostics routes share the FastAPI app, the SSE bridge to Redis,
and the privacy filter. The privacy filter is the load-bearing
boundary — it has to be at the bridge layer (not just in templates)
so a future bug in a template can't leak content.

## What Changes

- New top-level package `kaine.nexus`:
  - `app.py` — FastAPI app factory + uvicorn entrypoint. Two
    routers, mounted at `/` (conversation) and `/diagnostics`.
    The privacy filter is bound once at startup and consulted on
    every SSE message before send.
  - `config.py` — `NexusConfig` (host, port, conversation_enabled,
    diagnostics_enabled, dev_content_override (default False),
    conversation_history_lookback).
  - `privacy.py` — `PrivacyFilter` with two behaviors: `filter_for_
    conversation()` permits message bodies; `filter_for_diagnostics()`
    strips message text, belief bodies, memory text, internal
    speech, affect reasons — even nested in metadata — keeping only
    counts/rates/ids/timestamps.
  - `bridge.py` — `BusBridge` that runs as an asyncio task,
    subscribes to relevant streams, passes events through the
    privacy filter, and fans them out to per-client SSE queues.
  - `conversation.py` — router for the conversation surface
    (entity name, sleep status, external speech stream, SSE).
  - `diagnostics.py` — router for diagnostics (module list,
    soma wellness summary, cycle rates, slip metrics, fork list,
    adapter list, SSE for live metrics).
  - `templates/` — Jinja templates (conversation.html,
    diagnostics.html, _base.html, partials).
  - `static/` — minimal CSS, a tiny SSE client JS for live
    updates. No build step. No npm.
  - `__main__.py` — `python -m kaine.nexus` boots uvicorn against
    `[nexus]` config.
- `[nexus]` block in `config/kaine.toml` filled in (host, port,
  surface toggles, dev override).
- Tests: privacy-filter unit tests (boundary is the most important
  test surface), router smoke tests via `httpx.AsyncClient` against
  the FastAPI app with a fake bus, SSE event-format tests.

## Capabilities

### New Capabilities

- `nexus-conversation` — conversation surface route, entity-name
  lookup from Eidolon serialize, sleep-badge lookup from Hypnos.
- `nexus-diagnostics` — diagnostics surface route, metric
  aggregation from soma/cycle/forks/adapters.
- `nexus-privacy` — boundary enforcement (the load-bearing
  invariant for the entire UI).

### Modified Capabilities

None — Nexus is read-only against the bus and against module
serialize() outputs; it modifies no module behavior.

## Impact

- **New deps:** `fastapi`, `uvicorn[standard]`, `jinja2`. All
  pure-Python or trivially-installable. Documented in
  DEPENDENCIES.md. No build tooling.
- **Repo:** adds `kaine/nexus/*.py`, `kaine/nexus/templates/*.html`,
  `kaine/nexus/static/*`, `tests/test_nexus_*.py`. Updates
  `pyproject.toml` packages and `config/kaine.toml`.
- **No runtime impact on the cognitive cycle.** Nexus is a
  read-only observer. First boot does NOT start Nexus.
