## 1. Package + deps

- [x] 1.1 Add `fastapi`, `uvicorn[standard]`, `jinja2` to project deps
- [x] 1.2 Add `kaine.nexus` to setuptools packages
- [x] 1.3 `kaine/nexus/__init__.py` re-exports

## 2. Config

- [x] 2.1 Flesh out `[nexus]` block in `config/kaine.toml`
- [x] 2.2 `kaine/nexus/config.py` — `NexusConfig` dataclass + `load_nexus_config`

## 3. Privacy boundary

- [x] 3.1 `kaine/nexus/privacy.py` — `PrivacyFilter` with conversation/diagnostics behaviors
- [x] 3.2 Tests covering nested-payload stripping, dev override, conversation passthrough

## 4. Bus bridge

- [x] 4.1 `kaine/nexus/bridge.py` — `BusBridge` subscribes to streams, applies filter, fans out to per-client SSE queues
- [x] 4.2 Tests with fake bus

## 5. Conversation router

- [x] 5.1 `kaine/nexus/conversation.py` — entity-name lookup, sleep-badge, history backfill, SSE endpoint
- [x] 5.2 Templates: conversation.html, _base.html
- [x] 5.3 Router tests with httpx.AsyncClient

## 6. Diagnostics router

- [x] 6.1 `kaine/nexus/diagnostics.py` — module list, soma/cycle/forks/adapters aggregation, SSE, fork/merge controls
- [x] 6.2 Template: diagnostics.html
- [x] 6.3 Router tests asserting content is absent from responses

## 7. App + entrypoint

- [x] 7.1 `kaine/nexus/app.py` — FastAPI app factory wiring routers and bridge
- [x] 7.2 `kaine/nexus/__main__.py` — uvicorn launcher

## 8. Static assets

- [x] 8.1 `kaine/nexus/static/style.css`
- [x] 8.2 `kaine/nexus/static/nexus.js` — tiny SSE client

## 9. Verification

- [x] 9.1 Full suite passes (615 / 8 skipped)
- [x] 9.2 `openspec validate nexus-ui --strict` clean
- [ ] 9.3 Commit, merge, archive, tag v0.8-nexus
