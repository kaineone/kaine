## 1. Package + state

- [ ] 1.1 Add `kaine.modules.praxis` to setuptools packages
- [ ] 1.2 Add `state/praxis/` to `.gitignore` (already covered by `state/`)

## 2. Whitelist

- [ ] 2.1 Implement `kaine/modules/praxis/whitelist.py` with `CommandWhitelist`, `WhitelistEntry`, match logic; tests for empty/match/reject/arg-pattern

## 3. Effectors

- [ ] 3.1 Implement `kaine/modules/praxis/effectors.py` with `Effector` protocol, `ActionRequest` / `ActionResult` types, and `FileWriteEffector`, `NotifyEffector`, `ShellEffector`
- [ ] 3.2 Tests covering each effector's success/failure paths, sandbox enforcement, whitelist enforcement

## 4. Audit log

- [ ] 4.1 Implement `kaine/modules/praxis/audit_log.py` with `ActionAuditLog.append(record)` — atomic JSONL append
- [ ] 4.2 Tests verifying record shape, no content leakage, atomic-append behavior

## 5. Module

- [ ] 5.1 Implement `kaine/modules/praxis/module.py` with `Praxis(BaseModule)` exposing `act(request) -> ActionResult` and `register_effector`. Publishes `praxis.action` events with diagnostics-only payload
- [ ] 5.2 Update `kaine/modules/__init__.py` exports

## 6. Config

- [ ] 6.1 Add `[praxis]` block to `config/kaine.toml` with defaults
- [ ] 6.2 Add `praxis = false` under `[modules]`

## 7. Module tests

- [ ] 7.1 `tests/test_praxis_module.py` covering full action flow against fakeredis: file write, notify, shell (using a deliberately-narrow test whitelist), audit log content exclusion, bus event content exclusion

## 8. Documentation

- [ ] 8.1 Write `kaine/modules/praxis/AUDIT.md` describing the threat model and whitelist invariants

## 9. Verification

- [ ] 9.1 Full unit suite passes
- [ ] 9.2 `openspec validate praxis --strict` clean
- [ ] 9.3 Commit, merge, archive change, drop branch
