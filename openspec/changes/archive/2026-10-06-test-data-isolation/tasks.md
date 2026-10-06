## 1. Isolation

- [x] 1.1 An autouse per-test data root (process root and `KAINE_DATA_ROOT` set to `tmp_path` and restored), with a `no_data_root` opt-out marker registered in `pyproject.toml`.
- [x] 1.2 A guard that fails any test that changes the checkout's `state/`, skipping `forks`, `models` and `_archive*`.
- [x] 1.3 `storage_step.MOUNTS_PATH`, plus an autouse fixture pointing it at an empty file, so no test discovers real disks.
- [x] 1.4 A guard over the real data-root candidates known at session start: the operator config's data root and the storage step's real-mount recommendation. It reads directory modification times only and stands down while a `kaine.cycle` process runs.
- [x] 1.5 Tests:
  - a test that tries to discover mounts sees none;
  - each guard fails a test that writes into a directory it watches, exercised with a temporary stand-in for the real root;
  - the full suite passes without writing anything to real data.
