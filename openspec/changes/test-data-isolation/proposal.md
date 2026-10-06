## Why

Tests have written into real KAINE data twice:
- **Before 2026-10-04:** stray stage, perception and consolidation files landed in the checkout's own `state/`. They were quarantined by hand on 2026-10-04.
- **2026-10-06:** the setup-spawn tests wrote 121 acknowledgement records into the operator's real data root on the bulk drive, and changed that directory's mode.

A stray stage or lineage file in a real data root is read at the next spawn. It can mark a fresh being as lived, or give it a test's developmental stage, so it is a welfare hazard as well as a mess.

Two gaps let this happen:
- No test-wide guard sets each test's data root to its own temporary directory, so a test that resolves a relative `state/` path writes into the checkout.
- The setup wizard's storage default reads the host's real mounts (`/proc/mounts`) and proposes `<largest data mount>/kaine`. A test that drives the wizard to a save therefore points everything after it at the operator's real data root. Setting `KAINE_DATA_ROOT` doesn't help here, because the saved config names the directory explicitly.

## What Changes

- **Every test gets its own data root.** An autouse fixture sets the process data root and `KAINE_DATA_ROOT` to the test's `tmp_path` and restores both afterwards. Tests of the no-root defaults opt out with `@pytest.mark.no_data_root`.
- **Tests cannot discover real disks.** The storage step reads mounts from a module constant (`MOUNTS_PATH`, default `/proc/mounts`). An autouse fixture points it at an empty file, so the wizard's default stays inside the test's directory. Tests of mount parsing pass their own file, as they do today.
- **Guards fail any test that writes to real data.** These are snapshotted (modification times and sizes only, never file contents), skipping `_archive*`:
  - the checkout's `state/`;
  - the checkout's `config/`, which holds the operator's real `secrets.toml` and overlay;
  - every real data root known when the session starts (the operator config's configured data root, and the storage step's recommendation from the real mounts). The whole root is watched, except the operator's tooling and cache directories (`models`, `build-cache`, `scratch`, `abliteration`, `_nonresearch_artifacts`, `k1jev*`). Entity data is never skipped.

  Each guard records every directory and every regular file as (modification time, size), so an append or an in-place rewrite is caught as well as a create, rename or delete. `forks/` and `models/` are seen at their top level and their immediate children, without walking into a preserved being.

  A test that changes any of them fails and names the directories it changed. The real-root guard stands down, with a single warning, while a `kaine.cycle` process is running, because a live entity legitimately writes there.
- **No change at runtime.** `MOUNTS_PATH` has the same default as today.

## Impact

- Code:
  - `tests/conftest.py`;
  - `kaine/setup/storage_step.py`: the `MOUNTS_PATH` constant only;
  - `pyproject.toml`: registering the `no_data_root` marker;
  - the tests that legitimately use the no-root defaults.
- Research impact: none. This touches tests only, apart from a constant whose default is unchanged.
