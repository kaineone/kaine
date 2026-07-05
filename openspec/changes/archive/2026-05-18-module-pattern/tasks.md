## 1. Base class

- [x] 1.1 Implement `kaine/modules/base.py` with `BaseModule` abstract class — name ClassVar, async lifecycle hooks, default workspace consumer task, helper `publish`, snapshot reconstruction
- [x] 1.2 Write `tests/test_module_base.py` covering name enforcement, publish routing, on_workspace dispatch, error tolerance, ser/de round-trip

## 2. Registry

- [x] 2.1 Implement `kaine/modules/registry.py` with `ModuleRegistry` — register, unregister, get, all_modules, active_streams; raises on duplicate registration
- [x] 2.2 Write `tests/test_module_registry.py` covering register, unregister, duplicate rejection, active_streams formatting, ModuleRegistryProtocol conformance

## 3. EchoModule canary

- [x] 3.1 Implement `kaine/modules/echo.py` recording snapshots and providing `publish_one(payload, salience)`
- [x] 3.2 Write `tests/test_phase_1_endtoend.py` wiring bus + cycle + Syneidesis + Registry + EchoModule on fakeredis; assert end-to-end delivery

## 4. Wiring

- [x] 4.1 Update `kaine/modules/__init__.py` exports
- [x] 4.2 Add `kaine.modules` to `pyproject.toml` packages list
- [x] 4.3 Add `[modules]` section to `config/kaine.toml` with `echo = false`

## 5. Verification

- [x] 5.1 Run unit tests; all pass (81 passed, 3 integration skipped 2026-05-18)
- [x] 5.2 Run end-to-end test against fakeredis; passes
- [ ] 5.3 `openspec validate module-pattern --strict` clean
- [ ] 5.4 Commit; rename branch from phase-1.1-event-bus to phase-1-scaffolding (purely cosmetic); tag `v0.1-scaffolding`

## 6. Bus subscriber fix discovered during Phase 1.4

- [x] 6.1 `AsyncBus.subscribe_workspace` now resolves `"$"` to a concrete entry id up front and polls (50 ms) instead of relying on Redis `XREAD BLOCK`, so fakeredis-backed tests behave deterministically. New public helper `AsyncBus.current_workspace_id()` lets `BaseModule.initialize()` capture the cursor before starting its consumer task.
