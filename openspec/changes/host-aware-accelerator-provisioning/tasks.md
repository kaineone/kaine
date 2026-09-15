## 1. Host probe: unified-memory classification in `describe_host()`

This section extends `describe_host()` to classify accelerator memory as discrete, unified, or unknown, reporting per-pool figures with provenance and degrading gracefully on probe failure.

- [x] 1.1 Add unified-memory detection helpers to `kaine/hardware.py` (Tegra via device-tree `compatible`/model, Apple Silicon via platform + arm64 + MPS, AMD APU via sysfs/`rocminfo` integrated heuristic), each returning a verdict plus provenance; unit-test them against checked-in fixture snapshots of `/proc`, `/sys`, and the device tree.
- [x] 1.2 Extend the `describe_host()` schema with `memory.state`, `memory.pools` (vram and/or system), per-figure `provenance`, and explicit `unknown_reason` markers; keep all existing keys and values identical for discrete hosts.
- [x] 1.3 Guard every new probe call so `describe_host()` can never raise; add fault-injection tests that monkeypatch NVML/os/file access to raise and assert graceful `unknown` degradation.
- [x] 1.4 Add JSON round-trip tests for `describe_host()` across all host fixtures (x86_64 dual-GPU NVIDIA, Jetson/Tegra, Apple Silicon, AMD APU, ROCm dGPU, XPU, CPU-only).
- [x] 1.5 Audit existing `describe_host()` consumers for assumptions that VRAM is always present and fix them to handle `unified` and `unknown` states (the gpu-preflight consumer is covered in section 3).

## 2. Host-aware CUDA wheel index resolution

This section makes `scripts/install.sh` resolve the CUDA wheel index at install time from an ordered fallback table keyed on host probes, with an operator override and unchanged force-flag behavior.

- [x] 2.1 Implement a probe collector (machine architecture via `uname`, driver CUDA version from the `nvidia-smi` header, compute capability via `nvidia-smi --query-gpu=compute_cap` with a torch fallback, unified-memory-ness via `kaine.hardware`) exposed as a JSON-emitting CLI entry point callable from `install.sh`; unit-test each probe against mocked command outputs including failure modes.
- [x] 2.2 Encode the ordered fallback table as a single source of truth (data, not scattered shell conditionals) with first-match-wins resolution and the terminal CPU row; unit-test every row plus the ordering property (an earlier row shadows an overlapping later row).
- [x] 2.3 Replace the hardcoded `NVIDIA_INDEX_URL` logic in `scripts/install.sh` with the resolver call; log probe values, matched row key, and resolved URL; add a pip-shim integration test (fake `pip`, `nvidia-smi`, and `uname` on PATH) asserting the `--index-url` actually passed to pip for each scenario above.
- [x] 2.4 Add `--index-url` parsing and precedence (override > table > terminal fallback) to `scripts/install.sh`, with log lines distinguishing operator-provided from resolved URLs; extend the pip-shim test to cover the override and ignore-with-notice paths.
- [x] 2.5 Add pip-shim regression tests asserting identical pip arguments for `--cpu`, `--rocm`, `--xpu`, and `--mps` before and after the change, and that `--cuda` resolves through the table (with the legacy-cu128 warning path when the probe is insufficient).

## 3. `gpu-preflight` three-state memory gate

This section reworks the `gpu-preflight` memory gate into three states — known-discrete, known-unified, and unknown — so unknown memory never blocks boot by itself.

- [x] 3.1 Feed the gate from `describe_host()`'s memory classification instead of raw NVML figures, mapping discrete/unified/unknown to the three gate states.
- [x] 3.2 Implement the three-state decision logic and extend the gate report with `memory_state`, the figure and threshold applied, provenance, and annotation fields.
- [x] 3.3 Unit-test all five scenarios, including a snapshot regression proving the known-discrete path is identical to pre-change behavior.
- [x] 3.4 Update the gate's help text and docs to state the three states and the never-refuse-on-unknown rule.

## 4. First-run wizard mismatch detection and consented corrective install

This section adds accelerator/runtime mismatch detection to the first-run wizard and gates any corrective install behind explicit operator consent.

- [x] 4.1 Implement a pure mismatch evaluator `(driver_cuda_version, torch_cuda_version, compute_capability, arch_list) -> {compatible | ptx_jit | mismatch(reasons)}`; unit-test exact SASS match, same-major PTX, cross-major PTX, and hard-mismatch cases.
- [x] 4.2 Wire the evaluator into the first-run wizard: gather probes, render detected-versus-expected, and gate the corrective install behind an explicit consent prompt whose default is decline.
- [x] 4.3 Implement the consented corrective install (invoke the installer with the resolved index or appropriate flavor) followed by re-validation of `torch.version.cuda` and arch coverage; abort cleanly with guidance if re-validation still fails.
- [x] 4.4 Record the mismatch, consent decision, and outcome in wizard state and logs, including the continue-on-decline path with warning.
- [x] 4.5 Add an end-to-end wizard test with simulated probes covering all five scenarios, asserting the corrective install runs with the expected `--index-url` on consent and that nothing runs on decline.

## 5. Documentation and operator visibility

This section documents the provisioning behavior for operators and keeps the docs in sync with the implementation via a cross-check test.

- [x] 5.1 Write the operator doc page covering the fallback table, `--index-url`, the three preflight memory states, unified-memory classification and provenance, and per-platform notes (Jetson, AMD APU, Apple Silicon); generate the table section from the implementation to prevent drift.
- [x] 5.2 Add the docs cross-check test and update the installer help text.

## 6. Cross-host regression suite

This section locks in current behavior across all supported host classes with golden regression fixtures.

- [ ] 6.1 Capture golden fixtures (describe_host JSON, resolver decision, preflight report) for x86_64 dual-GPU NVIDIA, ROCm, XPU, MPS, and CPU-only hosts, plus Jetson and AMD APU, from pre-change behavior where applicable.
- [ ] 6.2 Add a cross-host regression module replaying the fixtures through `describe_host()`, the resolver, and `gpu-preflight`, asserting the five scenarios above.
- [ ] 6.3 Run the full existing test suite and CI matrix, confirm zero regressions, and add the new regression module to CI.