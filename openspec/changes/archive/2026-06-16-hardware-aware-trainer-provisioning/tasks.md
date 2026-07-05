# Tasks (design-first proposal — implement on approval)

## 1. Vendor → guidance + real probe
- [x] 1.1 `kaine/setup/` helper: map `describe_host()["backend"]` → trainer guidance — `cuda`→Unsloth Studio, `rocm`→unsloth-core, `xpu`/`mps`/`cpu`→"no GPU trainer; voice-alignment training unavailable (phase stays off; metric still emits)". Each guide carries a doc URL + ordered steps (detect-and-guide; NEVER an auto-install of the multi-GB env).
- [x] 1.2 Real detection probe: given a candidate interpreter (the configured `trainer_python`, else the known Studio path, else none), check the interpreter exists AND `import unsloth` returns 0 via an explicit-argv subprocess (no shell, timeout). Never fake the result; report found/not-found + the path.

## 2. Wizard integration (Stage-2 / optional)
- [x] 2.1 A wizard step (after module selection, alongside the existing dependency step) that runs only when the operator indicates voice-alignment training is wanted: print the vendor-appropriate guidance, run the probe, and — when a usable interpreter is found — offer to record it as `[hypnos.voice_alignment].trainer_python` in the operator config (consented; reuse the operator-config writer). Never crash the wizard on a failed probe/guide.

## 3. Tests
- [x] 3.1 Mirror `tests/test_setup_wizard.py` / dependency-provisioning tests: vendor→guidance mapping for cuda/rocm/cpu (mock `describe_host`); probe found / not-found (mock interpreter + subprocess); consented trainer_python write; never-crash on probe failure; the unsupported-backend path reports "training unavailable" without error.

## 4. Docs
- [x] 4.1 Present-tense: `docs/hardware.md` + `docs/processes/voice-alignment.md` gain the vendor matrix (NVIDIA→Studio, AMD→unsloth-core, other→training unavailable) and how the wizard sets `trainer_python`. No personal paths in committed docs.

## 5. Validate
- [x] 5.1 Full suite green; import-linter green; `openspec validate hardware-aware-trainer-provisioning --strict`.
