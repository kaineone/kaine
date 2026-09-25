## 1. Coherence check

- [x] 1.1 Add `kaine/torch_stack.py` with `check_torch_stack(dists=None) -> list[str]` implementing the rules in design.md Decision 4, reading `importlib.metadata` by default.
- [x] 1.2 Add `tests/test_torch_stack.py` covering: coherent cu130 stack; torchvision pin mismatch; CUDA tag mismatch (cu130 vs cu128); tagged vs untagged mismatch; companions absent; torch absent.
- [x] 1.3 Run the check in `kaine/preboot.py` CONFIG SANITY: FAIL listing each problem, PASS with the stack versions when coherent, SKIP when torch is not installed; add a test.

## 2. Installers

- [x] 2.1 Both installers read the torch requirement from `pyproject.toml`; add a test asserting `install.py --print-torch-spec` and the spec used by `install.sh` equal the pyproject entry.
- [x] 2.2 Install `torch` and `torchvision` in one pip invocation from the resolved index (MPS: default index).
- [x] 2.3 Write `<venv>/kaine-torch-constraints.txt` after the torch step and pass `-c` to every later `pip install`.
- [x] 2.4 `--research`: install `torchaudio` from the same index (constrained) before the perception extras.
- [x] 2.5 Verify step runs `check_torch_stack()` and exits non-zero with the problems listed when it is not coherent.
- [x] 2.6 Honour `KAINE_VENV_DIR` in both installers.

## 3. Hermetic installer tests

- [x] 3.1 `tests/test_install_wheel_index.py` sets `KAINE_VENV_DIR` to a temp dir and asserts the repository `.venv/` is not modified.
- [x] 3.2 Update assertions for the combined `torch torchvision` install and the `-c` constraints flag.

## 4. Docs and verification

- [x] 4.1 Document the constraints file, `KAINE_VENV_DIR`, and the pre-boot check in `docs/hardware.md` (present tense).
- [x] 4.2 Full offline suite green; `openspec validate torch-stack-coherence --strict` passes.
