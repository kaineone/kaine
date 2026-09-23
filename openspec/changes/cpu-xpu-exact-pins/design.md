## Context

`resolve_index` already computes CPU pins when the CUDA ladder exhausts (`_newest_arch_version("cpu", arch, spec)` plus `_companion`). The cpu and xpu flavors never reach the resolver: the installers map them to a fixed index URL and install the tested range.

## Decisions

**Reuse the recorded data and the existing helpers.** A small `resolve_fixed_flavor(flavor, arch, spec=None, need_torchaudio=False)` uses `PUBLISHED`, `_newest_arch_version` and `_companion`. Selection mirrors the CUDA policy: the highest in-range torch for the architecture; with `need_torchaudio`, the highest in-range torch that has a torchaudio companion. The result has the same keys as the CUDA and ROCm results (`variant`, `index_url`, `torch_version`, `torchvision_version`, `torchaudio_version`, `selected_reason`, `warnings`, `selftest_required` = false), so the installers parse it with the code they already use.

**Refuse, do not fall back.** An xpu request on an architecture the xpu index does not serve returns `index_url` None and a warning. The installers stop before installing torch, as the ROCm path does. Silently installing CPU wheels for an explicit `--xpu` would hide the problem.

**MPS stays unpinned.** The default PyPI index is not recorded in `wheel_data`, and inventing pins without data would be a claim the code cannot back.

## Risks

- A cpu install now pins a specific torch where it previously took the newest in range. It is the same version pip would choose when the recorded data is current. `--verify-indexes` reports drift.
