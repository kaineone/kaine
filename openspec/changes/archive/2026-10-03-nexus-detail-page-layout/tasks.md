## 1. Layout
- [x] 1.1 `kaine/nexus/static/style.css`: `main` scrolls vertically; `.page` (not `.page--console`) takes natural height; `.page--console` keeps its fixed-screen sizing.
- [x] 1.2 `dl.kv`: `grid-template-columns: fit-content(50%) minmax(0, 1fr)`, labels wrap.
- [x] 1.3 `kaine/nexus/templates/_base.html`: render the right sidebar only when the `sidebar_right` block has content.

## 2. Auth script
- [x] 2.1 `kaine/nexus/static/nexus_auth.js`: remove the constant-copying loop.
- [x] 2.2 `tests/js/nexus_auth_harness.js`: the fake `EventSource` constants are non-writable (`Object.defineProperty`); the existing constant check still passes.

## 3. Tests
- [x] 3.1 The diagnostics page renders no right sidebar; the console renders one with the health board.
- [x] 3.2 A rendered-layout check in a real browser (Playwright driving the system Chrome, `browser-test` extra; skips without a browser): no board on the diagnostics page starts past the page's right edge, and each board's cards start below its title.
