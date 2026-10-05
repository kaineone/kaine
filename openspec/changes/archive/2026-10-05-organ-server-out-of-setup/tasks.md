## 1. Move
- [x] 1.1 `kaine/organ_server/lifecycle.py`, `served.py` and `device_map.py`, moved verbatim (AST-checked).
- [x] 1.2 `kaine/setup/organ.py` keeps download and revision state; `kaine/setup/model_server.py` is a CLI entry.
- [x] 1.3 Callers, tests and docs use the new modules.

## 2. Contract
- [x] 2.1 The edge contract forbids indirect imports, and every contract holds.
- [x] 2.2 `kaine.organ_server` and `kaine.organ_probe` are listed in the sidecar contract.
