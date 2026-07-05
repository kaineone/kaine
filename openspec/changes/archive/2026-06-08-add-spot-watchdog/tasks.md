# Tasks

## 1. BaseModule liveness/restart contract (`kaine/modules/base.py`)
- [ ] 1.1 Add `_last_heartbeat` (monotonic), `_beat()`, bump it in `_workspace_loop` after `on_workspace` and at the end of `publish`.
- [ ] 1.2 Add `heartbeat_age() -> float` and `health() -> dict` (name, heartbeat_age_s, tasks_total, tasks_done, tasks_failed) — pure, never raises.
- [ ] 1.3 Add `async restart()` (light: shutdown → fresh `_stopped`/cursor → initialize) and `holds_external_resources() -> bool` (default False).
- [ ] 1.4 Override `holds_external_resources()→True` on audition, vox, mnemos, empatheia, topos, nous, lingua, hypnos (one line each).

## 2. Registry + control attribution
- [ ] 2.1 `ModuleRegistry.replace(name, module)` (`kaine/modules/registry.py`) — validate name match, swap in place.
- [ ] 2.2 `CycleControl.source` field (`operator`|`spot`) in `kaine/cycle/control_state.py` (`from_dict`/`to_dict`/`freeze(source=...)`), default `operator`, backward-compatible read.

## 3. Spot core (`kaine/cycle/spot.py`, `kaine/cycle/escalation_state.py`)
- [ ] 3.1 `escalation_state.py`: atomic read/write/clear of `state/cycle/escalation.json` (operational fields only).
- [ ] 3.2 `SpotConfig.from_section` ([spot]: enabled, poll_interval_s, heartbeat_timeout_s, max_restart_attempts, restart_backoff_s, per_module_timeout_s).
- [ ] 3.3 `Spot.assess()` (alive/dead/hung with crash-primary, hang-gated, sleep-gate via hypnos.is_sleeping); clock injected for tests.
- [ ] 3.4 Recovery: freeze (control source=spot) → pre-restart snapshot → restart (light, else heavy via injected `rebuild_module` + `registry.replace` + rewire + restore) → resume own freeze on success; one incident per poll.
- [ ] 3.5 Escalation at 5 failures: final snapshot → shutdown all → write escalation.json → publish `spot.status(critical)` → log CRITICAL → signal halt.
- [ ] 3.6 Publish `spot.status` and `spot.log` events to `spot.out` on each transition; wrap `run()` so an internal error halts rather than dies silently.

## 4. Boot/entrypoint wiring (`kaine/boot.py`, `kaine/cycle/__main__.py`)
- [ ] 4.1 Factor `rewire_module(registry, name, kaine_config)` out of `build_registry` (self-hearing gate, lingua self-model, oscillators).
- [ ] 4.2 Entrypoint: build `ForkManager`, a `rebuild_module` closure (mirrors `build_registry`/Hypnos second pass), parse `[spot]`, construct `Spot`, create `spot_task` next to `cycle_task`/`freeze_task`, await it in `finally`.
- [ ] 4.3 `clear_escalation()` at clean boot (next to `unfreeze()`); thread an escalation non-zero exit code through `_boot_and_run`/`main`; add `spot_state`/`spot_escalated` to runtime.json.

## 5. Nexus operator feedback
- [ ] 5.1 `health.py`: add a `spot` block to `snapshot()` derived from control.json(source)+escalation.json (state ok/recovery/critical, module, attempts, max_attempts, message, snapshot_id).
- [ ] 5.2 `kaine/nexus/__main__.py`: add `spot.out` to `DEFAULT_DIAGNOSTICS_STREAMS`.
- [ ] 5.3 Templates: alert-border overlay in `_base.html` (`data-state`), `_spot_banner.html`, `#spot-console` panel in `diagnostics.html`.
- [ ] 5.4 `style.css`: yellow(recovery)/red(critical) border using `--degraded`/`--down`; pulse gated by `prefers-reduced-motion`; console line colors.
- [ ] 5.5 `nexus.js`: subscribe to `spot.status` (set border/banner) and `spot.log` (append console); paint authoritative state from health.json on load/reconnect.

## 6. Config
- [ ] 6.1 `[spot]` section in `config/kaine.toml`, shipped `enabled = false`.

## 7. Tests
- [ ] 7.1 `test_base_heartbeat.py` (beat on publish/on_workspace, health/heartbeat_age shapes, light restart round-trip).
- [ ] 7.2 `test_spot_liveness.py` (dead on task exception / self-exit; alive for quiet beating module; hung only when stale+running+not-sleeping; sleep gate).
- [ ] 7.3 `test_spot_restart.py` (light recreate; heavy swap via replace + restore reseed; Hypnos sibling re-fetch; rewire re-attaches gate/oscillator).
- [ ] 7.4 `test_spot_escalation.py` (exactly 5 attempts; pre-restart + escalation snapshots; shutdown-all; escalation.json fields; halt/non-zero; no auto-retry).
- [ ] 7.5 `test_spot_freeze.py` (control source=spot; never clears operator freeze; resume only own freeze).
- [ ] 7.6 `test_spot_config.py` (defaults + per-module overrides; unknown keys rejected).
- [ ] 7.7 Extend `test_zero_persistence_invariant.py` to include `escalation.json`; extend the shipped-config all-off guard for `[spot].enabled = false`.
- [ ] 7.8 Extend `tests/test_nexus_routers.py` (health.json `spot` block; `/diagnostics/` renders border `data-state` + `#spot-console`; `spot.out` in diagnostics streams).

## 8. Verify
- [ ] 8.1 `.venv/bin/pytest -q -p no:cacheprovider` green.
- [ ] 8.2 Live `[spot].enabled=true` smoke: Spot starts, detects an injected dead task, freezes via control.json, restarts a pure module, and (forced-fail) writes escalation.json + exits non-zero — WITHOUT running the cognitive cycle / entity boot.
- [ ] 8.3 `openspec validate add-spot-watchdog --strict` passes.
