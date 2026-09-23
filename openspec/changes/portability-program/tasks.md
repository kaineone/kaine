## 0. Phase 0 — honest claims

- [x] 0.1 Rewrite the `docs/deployment-tiers.md` capability matrix and intro to state today's reality: torch required at every tier today (Soma/Chronos CfC, the MiniLM embedders); the modules each profile disables; "retired phone" and Pi-class hosts marked as the program target with the phase that reaches them.
- [x] 0.2 Align `docs/getting-started.md` and `docs/hardware.md` with that matrix.
- [x] 0.3 Fix the stale `~3.33 Hz` / `processing_rate_hz = 3.333` statement in `docs/deployment-topologies.md` (processing runs at 10 Hz; conscious access at 3.33 Hz).
- [x] 0.4 Correct the `config/profiles/tier0.toml` comment that claims to slow the subjective clock (it only disables the oscillator).
- [x] 0.5 `tests/test_setup_wizard.py`: write to `tmp_path`, not a fixed `/tmp` path.
- [x] 0.6 `tests/test_import_boundary_contracts.py`: fall back to `sys.executable -m importlinter`, not a bare `python`.

## 1. Program record

- [x] 1.1 `design.md` with the per-module audit, the phase plan, and the model ladder with sources and licence notes.
- [ ] 1.2 Open one design-first change per later phase when its turn comes.
