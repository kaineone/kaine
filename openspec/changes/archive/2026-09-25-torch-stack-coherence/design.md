## Context

`scripts/install.sh` and `scripts/install.py` are parallel installers (bash and Python) that choose a PyTorch wheel index for the host (`kaine/wheel_index.py`) and then run `pip install -e ".[test]"`. `pyproject.toml` lists `torch>=2.14.0,<3` as a base dependency (raised by a dependency bump). `torchvision` 0.29.0 declares `Requires-Dist: torch (==2.14.0)`. `torchaudio` is in maintenance: the newest build is 2.11.0 and its metadata declares no torch requirement, so pip cannot catch a torchaudio/torch mismatch; only the CUDA local tag reveals it. KAINE never imports torchvision or torchaudio directly; `transformers` imports torchvision when present, and `funasr` (audio extra) imports torchaudio.

## Decisions

**1. Read the torch requirement from `pyproject.toml`.** The installers parse `[project].dependencies` with `tomllib` (Python 3.11+; install.sh calls the chosen interpreter) and take the `torch` entry. A test asserts both installers resolve the same spec as `pyproject.toml`. This makes a future dependency bump automatically consistent.

**2. Install `torch torchvision` in one invocation from the resolved index.** pip then resolves torchvision against the torch it is installing, from the same CUDA build. torchaudio is not added to the default install because the default install does not need it and its versions lag torch.

**3. Constraints file, not version pins in pyproject.** After the torch step (installed or skipped as already correct), the installer writes `<venv>/kaine-torch-constraints.txt` with `name==version` lines for each of `torch`, `torchvision`, `torchaudio` that is installed, taken from `importlib.metadata`, and passes `-c <file>` to every later `pip install`. Pins in `pyproject.toml` would break CPU/ROCm/XPU/Jetson hosts whose wheels carry different versions.

**4. Coherence check reads metadata only.** `kaine/torch_stack.py` exposes `check_torch_stack(dists=None) -> list[str]` returning human-readable problems (empty = coherent). It uses `importlib.metadata` so it is cheap and safe in the pre-boot sweep. Rules: (a) if torchvision or torchaudio declares `torch==X`, the installed torch base version must equal X; (b) the local version tags (the part after `+`) of installed torch, torchvision and torchaudio must be identical when all present carry one; a missing tag on one package while another has a CUDA tag is a mismatch; (c) absent companions are not problems. `dists` is injectable for tests.

**5. Venv override.** `KAINE_VENV_DIR` (absolute or repo-relative) replaces the hard-coded `.venv` in both installers. The installer tests set it to a directory under `tmp_path`, and additionally assert the repository `.venv` mtime/listing is unchanged, so a regression that touches the developer environment fails loudly.

## Risks

- A host with an externally managed torch (Jetson system wheels) must still be honoured: the existing "already installed at the right flavor → skip" path is kept, and the constraints file then pins whatever is installed.
- torchaudio 2.11 against torch 2.14 imports and resamples correctly on the development host (verified), but it is not guaranteed for every future torch; the coherence check will flag tag mismatches, not ABI breakage.
