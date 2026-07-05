# Tasks

## 1. Multi-vendor device abstraction (`kaine/hardware.py`)
- [ ] 1.1 Add `xpu` / `xpu:N` as a recognized device string (`_BASE_DEVICES`, an `_XPU_INDEXED_RE`, `_validate_device_string`).
- [ ] 1.2 Add `_xpu_device_count()` and `available_xpu_devices()` mirroring the CUDA helpers, fully guarded.
- [ ] 1.3 `detect_device()` priority cuda > xpu > mps > cpu (CUDA path covers AMD ROCm automatically).
- [ ] 1.4 `select_device()` / `resolve_device()` handle `xpu` and `xpu:N` (strict raise vs graceful fallback) like the cuda branches; update `_safe_fallback`.
- [ ] 1.5 `describe_host()` adds `backend` (rocm/cuda/xpu/mps/cpu), `hip_version`, `xpu_available`, `xpu_count`, `xpu_names`, `xpu_devices` — without removing any existing key; stays JSON-serializable and never raises.
- [ ] 1.6 Update the module docstring to note ROCm/XPU/MPS are now handled.

## 2. Installer multi-vendor probe (`scripts/install.sh` + `scripts/install.py`)
- [ ] 2.1 Add `--rocm`, `--xpu`, `--mps` flags (and help text) alongside `--cuda` / `--cpu`.
- [ ] 2.2 Detection order when unforced: NVIDIA → AMD (`rocm-smi` / `/opt/rocm`) → Intel (`xpu-smi` / `sycl-ls`) → macOS arm64 (MPS) → CPU.
- [ ] 2.3 Wheel index per flavor: cuda→cu128, rocm→rocm6.2, xpu→xpu, cpu→cpu; mps installs the default PyPI wheel (no `--index-url`).
- [ ] 2.4 Idempotent re-run flavor check recognizes rocm (HIP), xpu, mps, cuda, cpu.

## 3. Tests (`tests/test_hardware.py`)
- [ ] 3.1 Mocked XPU host: `detect_device`/`select_device`/`resolve_device` return `xpu`; `xpu:N` out-of-range raises (strict) / falls back (resolve).
- [ ] 3.2 Mocked ROCm host: `describe_host()["backend"] == "rocm"`, `hip_version` set; selection still uses cuda strings.
- [ ] 3.3 `describe_host()` carries all new + all existing keys; JSON-serializable; graceful when a probe raises.

## 4. Docs — generalize the rig
- [ ] 4.1 Replace exact GPU/CPU/RAM models with role-based requirements in `docs/tech-choices.md`, `docs/getting-started.md`, `docs/KAINE_Paper.md`, and comment-only in `config/kaine.toml`, `kaine/modules/hypnos/voice_alignment.py`, `kaine/modules/lingua/ABLITERATION.md`.
- [ ] 4.2 Remove personal host names / IP (machine hostnames, a tailnet IP) → operator placeholders in `docs/CONNECTION_GUIDE.md`, `docs/modules/mundus.md`.

## 5. Docs — multi-GPU matrix + roadmap
- [ ] 5.1 Add a GPU / accelerator backend support matrix (CUDA / ROCm / XPU / MPS / CPU) to `docs/getting-started.md`; keep Speaches CPU+medium.en and `:8000/v1/models` intact.
- [ ] 5.2 Add a clearly-marked post-research roadmap (distributed computing; SBCs / upcycled smartphones / RISC-V) cross-referencing `distributed-substrate` and `portability-tiers`.
- [ ] 5.3 Generalize "Raspberry Pi" naming → SBC tiers in `openspec/changes/portability-tiers/` and `openspec/changes/distributed-substrate/`.

## 6. Verify
- [ ] 6.1 `.venv/bin/pytest -q -p no:cacheprovider` green.
- [ ] 6.2 `describe_host()` still works on the real host; install scripts pass syntax checks.
- [ ] 6.3 Grep clean of removed specs (GPU model names, personal hostnames, IPs; brand "Pi"); `config/kaine.toml` diff is comments-only.
- [ ] 6.4 `openspec validate generalize-hardware-and-multi-gpu --strict` passes.
