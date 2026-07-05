## 1. Interfaces

- [x] 1.1 Define `kaine/cycle/protocols.py` with `SyneidesisProtocol`, `ModuleRegistryProtocol`, `CycleHook` (placeholder protocols the cycle calls into; real implementations land in later changes)
- [x] 1.2 Define `kaine/cycle/types.py` with `TickResult`, `WorkspaceSnapshot` dataclasses

## 2. Engine

- [x] 2.1 Implement `kaine/cycle/engine.py` with `CognitiveCycle` class — async `run_forever`, `tick`, `pause`, `resume`, `set_processing_rate`, `set_experiential_rate`, `shutdown`
- [x] 2.2 Implement per-tick flow: gather reads from registered streams in parallel, hand collected events to Syneidesis collaborator, optionally call `bus.publish_workspace`, publish latency event
- [x] 2.3 Implement experiential accumulator so any processing/experiential ratio works without integer truncation
- [x] 2.4 Implement `CycleHooks` registry with on_pause / on_resume / on_shutdown firing

## 3. Tests

- [x] 3.1 Write `tests/test_cycle_rates.py` with a fake clock (monkeypatched `asyncio.sleep`) exercising pacing, rate decoupling, slip recording
- [x] 3.2 Write `tests/test_cycle_modules.py` covering quiet module skip, erroring-module tolerance, dynamic module add/remove
- [x] 3.3 Write `tests/test_cycle_hooks.py` covering hook order, hook errors not stopping subsequent hooks

## 4. Integration

- [x] 4.1 Update `config/kaine.toml`'s `[cycle]` section if the engine surfaces new knobs (no new knobs; existing rates suffice)
- [x] 4.2 Run unit tests; all pass (42 passed, 3 integration skipped 2026-05-18)
- [ ] 4.3 Commit and mark tasks complete in this file
- [ ] 4.4 `openspec validate cognitive-cycle --strict` clean
