## Why

The installers pin torch, torchvision and torchaudio exactly for CUDA and ROCm, but the cpu and xpu flavors install from a fixed index with only the tested range. Consequences:

- A re-run with `torchaudio` present uninstalls it and downloads it again every time, because no pin exists to compare it with.
- The unpinned `torchaudio` that comes back is the newest one the index offers (2.11.0), which declares no torch dependency, so it can end up paired with an older installed torch that it was never built against.
- The spec already promises "the exact newest in-range torch" for CPU hosts, which the cpu path does not deliver.

`kaine/wheel_data.py` already records the cpu index (x86_64 and aarch64) and the xpu index (x86_64) with torchvision and torchaudio companions, so the resolver can pin these flavors the way it pins CUDA and ROCm.

## What Changes

- `python -m kaine.wheel_index --flavor cpu|xpu` resolves the newest in-range torch that index publishes for the host architecture, with its recorded companions. With `--need-torchaudio` it prefers a version that has a torchaudio companion. It returns no index and a warning naming the flavor and architecture when the index publishes no in-range torch for it (for example xpu on aarch64). The release-timing torchaudio pairing warning applies as it does for CUDA.
- Both installers call it for the cpu and xpu flavors, install the exact pins, write them to the constraints file, and use the existing keep/replace rule for torchaudio, so a matching torchaudio is kept on re-runs. An xpu host with no published wheel is refused before torch is installed.
- The mps flavor stays unpinned (no MPS wheel data is recorded); the spec says so instead of claiming an exact pin.
- The install requirement's flavor-change scenario is corrected: a flavor mismatch forces a reinstall; a non-PyTorch `--index-url` on its own does not.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `dynamic-hardware`: cpu and xpu installs are pinned exactly; mps is stated as unpinned; a matching CPU torchaudio is kept on re-runs.

## Impact

- `kaine/wheel_index.py`, `scripts/install.sh`, `scripts/install.py`
- `docs/accelerator-provisioning.md`
- Tests: `tests/test_wheel_index_review.py` (or a new resolver test file), `tests/test_install_wheel_index.py`, `tests/test_install_py_parity.py`
- No entity boot needed.
