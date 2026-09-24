## 1. Plugin

- [x] 1.1 `config.py`: `overlay_from_mapping(raw)` shared by `load_overlay(path)`.
- [x] 1.2 `plugin.py`: `make_plugin()`, `Cl1Plugin.seams`, `Cl1Plugin.injections`; lazy process-wide session and broker; territory reuse on repeated requests; accelerated-time guard; close at exit.
- [x] 1.3 `pyproject.toml` entry point; example config rewritten as a `[plugins.cl1]` block with only Chronos converted.

## 2. Tests

- [x] 2.1 Entry point declared in `pyproject.toml`.
- [x] 2.2 Seam selection, unimplemented backend, missing territory, empty selection opens no session.
- [x] 2.3 Accelerated-time guard.
- [x] 2.4 Three repeated Chronos injections reuse one territory and each network ticks.
- [x] 2.5 A plugin-supplied network drives stock kaine Chronos over the fake bus (forward prediction off until the kaine head-sizing fix is pinned).
- [x] 2.6 `load_overlay` reads the shipped example (both config forms; both at once rejected).

## 3. Follow-up (after kaine module-plugins merges)

- [x] 3.1 Move the kaine pin to the merge commit and add an end-to-end test through kaine's plugin loader; tick foundation task 5.1. Pinned to 7807555 (kaine PR #172); `tests/test_kaine_boot.py` boots through `load_plugins` and `build_registry`.
