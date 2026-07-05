## 1. Boot wiring

- [x] 1.1 `kaine/boot.py` — module factories + `build_registry`
- [x] 1.2 `kaine/cycle/__main__.py` — operator entrypoint with safety gate

## 2. Nexus real metrics

- [x] 2.1 `MetricsCollector` in `kaine/boot.py`
- [x] 2.2 Update `kaine/nexus/__main__.py` to use real metrics (via state/cycle/runtime.json)

## 3. Doc fixes

- [x] 3.1 Confirm SECURITY.md only references kaine/bus/AUDIT.md (no false claim)
- [x] 3.2 Remove `state/bus/AUDIT.log` from FIRST_BOOT.md
- [x] 3.3 Update FIRST_BOOT.md Step 3 to point at `python -m kaine.cycle`

## 4. Tests

- [x] 4.1 `tests/test_boot_wiring.py` — build full registry from config (19 tests)
- [x] 4.2 `tests/test_cycle_entrypoint.py` — verify the entrypoint refuses without env var

## 5. Latent bug fixed during fixup

- [x] 5.1 `kaine/modules/mnemos/module.py` — guard against unloaded embedder.latent_dim raising at construction

## 6. Verification

- [x] 6.1 Full suite passes (644 / 8 skipped)
- [x] 6.2 `openspec validate v1-boot-wiring --strict` clean
- [ ] 6.3 Commit, merge, archive, tag v1.0.1-ready
