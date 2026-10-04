# One installer

## Why

The complexity audit of 2026-10-03 (W10) found two installers: `scripts/install.sh` (970 lines) and `scripts/install.py` (1,497 lines), a Python port kept for macOS, zsh-only and BSD hosts. A parity test existed only to catch drift between them. The operator decided on 2026-10-04 that no host needs the Python port.

One dependency remained: the container image build called `install.py --print-index <flavor>` and `--print-torch-spec` for its PyTorch wheel index and torch requirement.

## What changes

- **`kaine/wheel_index.py`**, already the single source of wheel-index truth for `install.sh`, gains:
  - `IMAGE_INDEX_BY_FLAVOR`, the fixed per-flavor index a container build uses;
  - `image_index(flavor)` and `torch_requirement(pyproject)`;
  - the CLI flags `--image-index FLAVOR` and `--torch-spec PATH`.

  `tomllib` is imported only inside `torch_requirement`, so the module still loads on a system Python older than 3.11.
- **The Dockerfile's two build stages** copy `wheel_index.py` and `wheel_data.py` into a bare package and run those flags.
  - Each flavor gets exactly the index the build stage got before: cuda `cu126`, cpu and xpu their indexes, mps and rocm the PyPI default.
  - The torch requirement is unchanged.
- **Retired:** `scripts/install.py` and `tests/test_install_py_parity.py`. The `install.py` cases of the wheel-index installer tests go, and their `install.sh` cases stay.
- **Docs and specs** describe one installer. The container docs describe the wheel-index flags.

## Impact

- **Behaviour:** none for `install.sh` hosts. Container builds get the same index and torch requirement for every flavor. A host that ran `python3 scripts/install.py` now runs `bash scripts/install.sh`.
- **Research:** none. The study image is not yet built; it will be built from main after this lands.
- **Recorded, not changed:** the experimental `rocm` image flavor installs torch from the default PyPI index, which serves CUDA builds. It was so before; making rocm images real needs ROCm hardware to validate.
