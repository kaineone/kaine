## 1. Package + config

- [ ] 1.1 Add `state/` to `.gitignore` (covers `state/eidolon/`)
- [ ] 1.2 Add `kaine.modules.eidolon` to setuptools packages
- [ ] 1.3 Add `[eidolon]` block to `config/kaine.toml`; add `eidolon = false` under `[modules]`

## 2. SelfModel document

- [ ] 2.1 Implement `kaine/modules/eidolon/document.py` with `SelfModel` dataclass (frozen), `load`, `save_atomic`, and `with_updates(...)` helpers
- [ ] 2.2 Tests covering empty default, JSON roundtrip, atomic save (write-then-rename), `with_updates` immutability

## 3. Drift detector

- [ ] 3.1 Implement `kaine/modules/eidolon/drift.py` with `DriftDetector` protocol + `SourceDistributionDrift` default (recent deque + cumulative Counter, symmetric KL with epsilon smoothing, threshold flagging)
- [ ] 3.2 Tests covering empty-state zero drift, stable-distribution low drift, novel-source high drift, window eviction, threshold semantics

## 4. Module

- [ ] 4.1 Implement `kaine/modules/eidolon/module.py` with `Eidolon(BaseModule)`. initialize loads JSON if present, starts internal-speech consumer task and periodic-save task; on_workspace updates drift detector + counts; shutdown forces final save
- [ ] 4.2 Update `kaine/modules/__init__.py` to export `Eidolon`

## 5. Tests

- [ ] 5.1 `tests/test_eidolon_module.py` (fakeredis): workspace updates drift; threshold crossing publishes diagnostics-only event; internal-speech increments counter; final save on shutdown; identity_history grows with drift; cap enforcement

## 6. Verification + tag

- [ ] 6.1 Full unit suite passes
- [ ] 6.2 `openspec validate eidolon --strict` clean
- [ ] 6.3 Commit, merge, archive change, drop branch
- [ ] 6.4 Tag `v0.3-cognition` (closes Phase 3)
