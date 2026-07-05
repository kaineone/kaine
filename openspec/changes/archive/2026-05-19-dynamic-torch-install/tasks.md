## 1. Install scripts

- [x] 1.1 Write `scripts/install.sh` with: venv discovery/creation, NVIDIA detection via `nvidia-smi`, wheel-index selection (cu128 default for NVIDIA, cpu otherwise), idempotent torch install, then `pip install -e .[test]`
- [x] 1.2 Write `scripts/install.py` mirroring the Bash logic for non-bash hosts
- [x] 1.3 Make both scripts executable

## 2. Hardware module

- [x] 2.1 Implement `kaine/hardware.py` with `detect_device`, `select_device`, and `describe_host`. `KAINE_FORCE_DEVICE` env-var override is honored at top of `select_device`.
- [x] 2.2 Update `kaine/__init__.py` to export `detect_device`, `select_device`, `describe_host` for convenience.

## 3. pyproject + packaging

- [x] 3.1 Add `torch>=2.5,<3` and `ncps>=1.0,<2` to `[project.dependencies]`; also added `numpy>=1.26,<3` to clear a torch startup warning and unlock array conversions
- [x] 3.2 Confirm setuptools `packages` list does not need a new entry (kaine.hardware is a flat module — already in `packages = ["kaine", ...]`)

## 4. Tests

- [x] 4.1 Write `tests/test_hardware.py` covering: detect returns one of the three values; select honors preferred when valid; select rejects unknown preferred; KAINE_FORCE_DEVICE wins; describe_host returns JSON-serializable dict with the documented keys (10 cases)

## 5. Install on this machine

- [x] 5.1 Run `bash scripts/install.sh` — picked cu128, downloaded torch 2.11.0+cu128 and CUDA libs, installed editable kaine
- [x] 5.2 Verified `torch.cuda.is_available() == True`; both RTX 4070 SUPER and RTX 3070 detected via `describe_host()`
- [x] 5.3 Full test suite passes (133 passed, 3 integration skipped 2026-05-19); also sanity-checked `ncps.torch.CfC` at units=16 → 11,456 params, well under the 100K cap

## 6. Documentation

- [x] 6.1 Update `SETUP.md` to point at the install script as the canonical install path
- [x] 6.2 Update `DEPENDENCIES.md` adding torch, ncps, and numpy with their roles

## 7. Verification

- [ ] 7.1 `openspec validate dynamic-torch-install --strict` clean
- [ ] 7.2 Commit, merge to main, drop branch
- [ ] 7.3 `openspec archive dynamic-torch-install` to land the dynamic-hardware spec in `openspec/specs/`
