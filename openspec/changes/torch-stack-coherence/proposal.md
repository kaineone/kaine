## Why

The PyTorch stack in a KAINE environment can silently fall out of step, and when it does, the modules that need `transformers` fail at boot while the offline test suite still passes. This has already happened on a development host: `torch` was upgraded to 2.14.0 while `torchvision` stayed at 0.26 (built for an older torch, cu128) and `torchaudio` stayed at a cu128 build. `import transformers.modeling_utils` then raises `RuntimeError: operator torchvision::nms does not exist`, which disables every MiniLM (Mnemos, Empatheia, Hypnos) and DINOv2 (Topos) path.

Four defects combine to produce this:

- The installers pin `torch>=2.5,<3` while `pyproject.toml` requires `torch>=2.14.0,<3`, so the later `pip install -e .` re-resolves torch from the default index and can replace the accelerator-specific wheel.
- The installers install `torch` alone, never `torchvision` or `torchaudio` from the same wheel index, so companions installed later come from a different index or CUDA build.
- Nothing pins the installed torch stack, so any later `pip install` of an extra may swap it.
- `tests/test_install_wheel_index.py` runs `scripts/install.sh` from the repository root. When the developer's `.venv/` already exists, `install.sh` uses `.venv/bin/pip` directly, bypassing the test's pip shim, so running the test suite executes real `pip install` commands against the developer's real environment (including `--index-url .../whl/cpu torch`). CI passes only because CI has no `.venv/`.

Nothing detects an incoherent stack before boot.

## What Changes

- **Installers use the project's torch requirement.** `scripts/install.sh` and `scripts/install.py` read the torch requirement from `pyproject.toml` rather than hard-coding a looser spec, and a test fails if they disagree.
- **Torch and torchvision install together from one index.** The installers install `torch` and `torchvision` in a single pip invocation from the resolved wheel index, so pip enforces torchvision's exact torch pin.
- **The installed torch stack is pinned for the rest of the install.** After the torch step, the installers write a constraints file recording the exact installed `torch`, `torchvision` and (if present) `torchaudio` versions, and pass it with `-c` to every later `pip install` so no extra can swap the stack.
- **`--research` installs `torchaudio` from the same index** before the perception extras, so `funasr` does not pull a mismatched build.
- **Installers accept a venv location override** (`KAINE_VENV_DIR`, default `.venv`). The installer tests point it at a temporary directory and never touch the developer's environment.
- **A torch-stack coherence check.** A new `kaine/torch_stack.py` inspects installed distribution metadata (without importing torch) and reports mismatches: a companion whose declared `torch==` pin differs from the installed torch, or local CUDA tags (`+cu130`, `+cpu`, …) that differ across the stack. The pre-boot sweep runs it under CONFIG SANITY and FAILS on a mismatch; the installers run it in their verify step and exit non-zero on a mismatch.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `dynamic-hardware`: add requirements for torch-stack coherence at install time, a hermetic installer test harness, and a pre-boot coherence check.

## Impact

- `scripts/install.sh`, `scripts/install.py`
- `kaine/torch_stack.py` (new), `kaine/preboot.py` (CONFIG SANITY check)
- `tests/test_install_wheel_index.py` (hermetic venv), `tests/test_torch_stack.py` (new), installer spec-parity test
- `docs/hardware.md` / `SETUP.md` install notes
- No entity boot is needed to verify this change.
