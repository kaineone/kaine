## 1. Implementation

- [x] 1.1 `pyproject.toml`: slim the base; add `core`, `memory`, `memory-edge`, `nexus`, `nvidia` and `full`; extend `vision`.
- [x] 1.2 `kaine/extras.py`: the requirement table, `check`, `format_missing`.
- [x] 1.3 `build_registry` and `python -m kaine.nexus` call the check and fail closed with the message.
- [x] 1.4 `scripts/install.sh` and `scripts/install.py`: `--extras`, conditional torch, the new verification.
- [x] 1.5 `docs/getting-started.md`: the extras table.

## 2. Verification

- [x] 2.1 Tests:
  - `check` with blocked imports (monkeypatched `find_spec`) reports exactly the missing extras for a config, including config-dependent rows (backend switches, capture);
  - `build_registry` refuses before building any module;
  - the table matches the modules' real imports;
  - Nexus refuses without `nexus`;
  - the installers' `--extras` parsing, and the verification step choosing the torch import.
- [x] 2.2 Offline suite green; `openspec validate slim-base-dependencies --strict`.
