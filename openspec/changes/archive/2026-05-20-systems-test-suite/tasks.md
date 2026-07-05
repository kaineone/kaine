## 1. Harness + marker

- [x] 1.1 `tests/systems/__init__.py`
- [x] 1.2 `tests/systems/_harness.py` — `SubsystemHarness` + helpers
- [x] 1.3 `tests/systems/conftest.py` — env-var skip markers
- [x] 1.4 Register `systems` marker in `pyproject.toml`

## 2. Core subsystems

- [x] 2.1 `test_bus_subsystem.py`
- [x] 2.2 `test_cycle_subsystem.py`
- [x] 2.3 `test_workspace_subsystem.py`

## 3. Module subsystems (all-local fake-backed)

- [x] 3.1 `test_soma_subsystem.py`
- [x] 3.2 `test_chronos_subsystem.py`
- [x] 3.3 `test_mnemos_subsystem.py`
- [x] 3.4 `test_eidolon_subsystem.py`
- [x] 3.5 `test_thymos_subsystem.py`
- [x] 3.6 `test_praxis_subsystem.py`
- [x] 3.7 `test_hypnos_subsystem.py`

## 4. Module subsystems (service-gated)

- [x] 4.1 `test_topos_subsystem.py`
- [x] 4.2 `test_nous_subsystem.py`
- [x] 4.3 `test_lingua_subsystem.py`
- [x] 4.4 `test_audio_in_subsystem.py`
- [x] 4.5 `test_audio_out_subsystem.py`

## 5. Cross-cutting subsystems

- [x] 5.1 `test_lifecycle_subsystem.py`
- [x] 5.2 `test_boot_subsystem.py`
- [x] 5.3 `test_nexus_subsystem.py`
- [x] 5.4 `test_sidecar_subsystem.py`

## 6. Operator docs

- [x] 6.1 Brief note in FIRST_BOOT.md pointing at `pytest -m systems`

## 7. Verification

- [x] 7.1 Full suite passes (731 / 12 skipped)
- [x] 7.2 `pytest -m systems` runs only the systems suite (50 / 4 skipped / 689 deselected)
- [x] 7.3 `openspec validate systems-test-suite --strict` clean
- [ ] 7.4 Commit, merge, archive
