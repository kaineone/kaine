## 1. Host probe: unified-memory classification in `describe_host()`

### Requirement: Unified-memory-aware host description
`kaine/hardware.py::describe_host()` SHALL classify the memory of every detected accelerator as `discrete`, `unified`, or `unknown`; SHALL report per-pool figures — VRAM total/free for discrete, system RAM total/available for unified — each accompanied by provenance naming the data source; SHALL emit explicit unknown markers (a `null` figure plus an `unknown_reason`) instead of silent zeros or omitted fields whenever a figure cannot be determined; SHALL remain fully JSON-serializable; and SHALL NOT raise under any probe failure, degrading to `unknown` instead.

#### Scenario: Discrete GPU reports VRAM pool with provenance
- **WHEN** `describe_host()` runs on a host with a discrete NVIDIA GPU and NVML returns memory information
- **THEN** the accelerator's memory state is `discrete` with a VRAM pool carrying total and free figures and provenance naming NVML, and every pre-existing `describe_host()` key keeps its previous value.

#### Scenario: Tegra/Jetson unified memory is reported instead of zeroed
- **WHEN** `describe_host()` runs on an NVIDIA Tegra/Jetson host where NVML reports "Not Supported" for memory and the device tree identifies a Tegra SoC
- **THEN** memory state is `unified` with a system-RAM pool carrying total and available figures and provenance recording both the meminfo source and the Tegra detection, and no zero or missing VRAM figure is presented as a valid discrete pool.

#### Scenario: Apple Silicon MPS host is classified unified
- **WHEN** `describe_host()` runs on Apple Silicon with MPS available
- **THEN** memory state is `unified` with system-pool figures and provenance, and the accelerator is still reported as MPS.

#### Scenario: AMD APU is classified unified
- **WHEN** `describe_host()` runs on a host whose only GPU is an integrated AMD APU sharing system RAM
- **THEN** memory state is `unified` with system-pool figures rather than missing or zero VRAM.

#### Scenario: Probe failure degrades to unknown without raising
- **WHEN** any memory probe (NVML, `/proc/meminfo`, sysfs, device tree) raises or returns an error during `describe_host()`
- **THEN** `describe_host()` returns normally, marks the affected figure `null` with an explicit `unknown_reason`, and no exception escapes `describe_host()`.

#### Scenario: Output stays JSON-serializable
- **WHEN** `describe_host()` output is passed to `json.dumps()` for every supported host fixture
- **THEN** serialization succeeds and the parsed structure compares equal to the original.

- [ ] 1.1 Add unified-memory detection helpers to `kaine/hardware.py` (Tegra via device-tree `compatible`/model, Apple Silicon via platform + arm64 + MPS, AMD APU via sysfs/`rocminfo` integrated heuristic), each returning a verdict plus provenance; unit-test them against checked-in fixture snapshots of `/proc`, `/sys`, and the device tree.
- [ ] 1.2 Extend the `describe_host()` schema with `memory.state`, `memory.pools` (vram and/or system), per-figure `provenance`, and explicit `unknown_reason` markers; keep all existing keys and values identical for discrete hosts.
- [ ] 1.3 Guard every new probe call so `describe_host()` can never raise; add fault-injection tests that monkeypatch NVML/os/file access to raise and assert graceful `unknown` degradation.
- [ ] 1.4 Add JSON round-trip tests for `describe_host()` across all host fixtures (x86_64 dual-GPU NVIDIA, Jetson/Tegra, Apple Silicon, AMD APU, ROCm dGPU, XPU, CPU-only).
- [ ] 1.5 Audit existing `describe_host()` consumers for assumptions that VRAM is always present and fix them to handle `unified` and `unknown` states (the gpu-preflight consumer is covered in section 3).

## 2. Host-aware CUDA wheel index resolution

### Requirement: Fallback-table wheel index resolution
`scripts/install.sh` SHALL NOT hardcode the CUDA wheel index; it SHALL resolve the index at install time by matching a documented, ordered fallback table — keyed on machine architecture, driver CUDA version, GPU compute capability, and unified-memory-ness — and selecting the first matching row; the table SHALL include the x86_64 CUDA 12.x and CUDA 13.x rows, the aarch64 SBSA row for compute capability ≥ 9.0, the aarch64 Tegra/Jetson unified row, and a terminal CPU-only fallback row; the resolver SHALL select an index whose CUDA version never exceeds the driver's; SHALL log the probe values, matched row key, and resolved URL; and SHALL apply the terminal fallback (CPU-only index with a prominent warning listing the missing probe values) when no row matches.

#### Scenario: x86_64 NVIDIA workstation default is unchanged
- **WHEN** installation runs on x86_64 with discrete NVIDIA GPU(s), a CUDA 12.x driver, and compute capability covered by the current default
- **THEN** the resolved index is the same cu128 index used today and the matched row key is recorded in the install log.

#### Scenario: CUDA 13.x driver no longer receives cu128 wheels
- **WHEN** the probe reports a CUDA 13.x driver on a CUDA-capable host
- **THEN** the resolver selects the table's CUDA 13 row and the resolved index is CUDA-13-compatible, never the cu128 index.

#### Scenario: Driver minor version bounds the index
- **WHEN** the probe reports a CUDA 12.4 driver
- **THEN** the resolved index publishes wheels built for CUDA ≤ 12.4 and never an index newer than the driver supports.

#### Scenario: aarch64 Jetson avoids the SBSA cu128 trap
- **WHEN** the probe reports aarch64, unified memory, and compute capability 8.7
- **THEN** the resolved index is the highest-priority row publishing aarch64 wheels containing sm_87 SASS or compute_87 PTX, and the cu128 SBSA index is not selected.

#### Scenario: aarch64 SBSA server keeps the SBSA index
- **WHEN** the probe reports aarch64 with compute capability ≥ 9.0
- **THEN** the resolved index is the aarch64 SBSA row whose wheels support sm_90 or newer, per the table order.

#### Scenario: Undeterminable probe falls back safely
- **WHEN** the probe cannot establish enough of architecture, driver CUDA version, compute capability, or unified-memory-ness to match any row
- **THEN** the installer uses the terminal CPU-only fallback, logs a prominent warning naming the missing probe values, and still honors `--index-url` when provided.

- [ ] 2.1 Implement a probe collector (machine architecture via `uname`, driver CUDA version from the `nvidia-smi` header, compute capability via `nvidia-smi --query-gpu=compute_cap` with a torch fallback, unified-memory-ness via `kaine.hardware`) exposed as a JSON-emitting CLI entry point callable from `install.sh`; unit-test each probe against mocked command outputs including failure modes.
- [ ] 2.2 Encode the ordered fallback table as a single source of truth (data, not scattered shell conditionals) with first-match-wins resolution and the terminal CPU row; unit-test every row plus the ordering property (an earlier row shadows an overlapping later row).
- [ ] 2.3 Replace the hardcoded `NVIDIA_INDEX_URL` logic in `scripts/install.sh` with the resolver call; log probe values, matched row key, and resolved URL; add a pip-shim integration test (fake `pip`, `nvidia-smi`, and `uname` on PATH) asserting the `--index-url` actually passed to pip for each scenario above.

### Requirement: Operator index override
`scripts/install.sh` SHALL accept `--index-url <url>`; the override SHALL take precedence over the fallback table whenever a CUDA index is used, SHALL be recorded in the install log as operator-provided, and SHALL be ignored with a logged notice when the selected flavor uses no CUDA index.

#### Scenario: Override wins over the table
- **WHEN** `install.sh` runs with `--index-url` on a host whose probe would resolve a different index
- **THEN** pip receives the operator URL and the log records that the override, not the table, determined the index.

#### Scenario: Override is ignored for non-CUDA flavors
- **WHEN** `install.sh` runs with `--index-url` together with `--cpu` (or `--rocm`, `--xpu`, `--mps`)
- **THEN** the non-CUDA index selection proceeds unchanged and a notice that `--index-url` was ignored is logged.

- [ ] 2.4 Add `--index-url` parsing and precedence (override > table > terminal fallback) to `scripts/install.sh`, with log lines distinguishing operator-provided from resolved URLs; extend the pip-shim test to cover the override and ignore-with-notice paths.

### Requirement: Force flag semantics preserved
The existing `--cpu`, `--cuda`, `--rocm`, `--xpu`, and `--mps` flags SHALL keep their exact current semantics: `--cpu` SHALL select the CPU index regardless of probe results; `--cuda` SHALL force the CUDA flavor using the host-resolved index when a row matches and the legacy cu128 index with a warning otherwise; `--rocm`, `--xpu`, and `--mps` SHALL select their respective flavors and SHALL NOT consult the CUDA table.

#### Scenario: --cpu ignores a present NVIDIA GPU
- **WHEN** `install.sh` runs with `--cpu` on a host where `nvidia-smi` succeeds
- **THEN** the CPU index is used and no CUDA table lookup occurs.

#### Scenario: --cuda routes through the resolver
- **WHEN** `install.sh` runs with `--cuda` on a supported NVIDIA host
- **THEN** the CUDA flavor is installed from the host-resolved index, or from `--index-url` when the override is given.

#### Scenario: --rocm/--xpu/--mps bypass the CUDA table
- **WHEN** `install.sh` runs with `--rocm`, `--xpu`, or `--mps` on their respective hosts
- **THEN** flavor selection and the resulting pip arguments are identical to pre-change behavior.

- [ ] 2.5 Add pip-shim regression tests asserting identical pip arguments for `--cpu`, `--rocm`, `--xpu`, and `--mps` before and after the change, and that `--cuda` resolves through the table (with the legacy-cu128 warning path when the probe is insufficient).

## 3. `gpu-preflight` three-state memory gate

### Requirement: Three-state memory gating
The `gpu-preflight` gate SHALL classify memory as `known-discrete`, `known-unified`, or `unknown`; SHALL keep known-discrete behavior unchanged (refuse boot when free VRAM is below `min_free_vram_gb`); SHALL apply `min_free_vram_gb` to available system memory for known-unified hosts; SHALL pass with an explicit annotation when memory is unknown; SHALL never refuse boot on unknowable memory alone; SHALL still enforce every other check when memory is unknown; and SHALL record the memory state, the figure used, its provenance, and any annotation in the gate report.

#### Scenario: known-discrete below threshold refuses unchanged
- **WHEN** the gate runs on a host with a discrete GPU whose free VRAM is below `min_free_vram_gb`
- **THEN** boot is refused with the same message and exit behavior as before this change.

#### Scenario: known-unified below threshold refuses with unified wording
- **WHEN** the gate runs on a unified-memory host whose available system memory is below `min_free_vram_gb`
- **THEN** boot is refused with a message naming the unified pool and the system-memory figure used.

#### Scenario: known-unified above threshold passes
- **WHEN** the gate runs on a unified-memory host with available system memory at or above `min_free_vram_gb`
- **THEN** boot proceeds and the report records state `known-unified` with the system figure and its provenance.

#### Scenario: unknown memory passes with annotation
- **WHEN** the gate runs on a host whose free memory cannot be determined
- **THEN** boot proceeds, the report carries an explicit unknown annotation with the reason, and no memory-based refusal occurs.

#### Scenario: unknown memory does not mask other failures
- **WHEN** memory state is unknown but another preflight check fails
- **THEN** boot is still refused for that check and the report shows both the other failure and the memory-unknown annotation.

- [ ] 3.1 Feed the gate from `describe_host()`'s memory classification instead of raw NVML figures, mapping discrete/unified/unknown to the three gate states.
- [ ] 3.2 Implement the three-state decision logic and extend the gate report with `memory_state`, the figure and threshold applied, provenance, and annotation fields.
- [ ] 3.3 Unit-test all five scenarios, including a snapshot regression proving the known-discrete path is identical to pre-change behavior.
- [ ] 3.4 Update the gate's help text and docs to state the three states and the never-refuse-on-unknown rule.

## 4. First-run wizard mismatch detection and consented corrective install

### Requirement: Consented accelerator/runtime mismatch remediation
The first-run wizard SHALL detect accelerator/runtime mismatches by comparing the probed driver CUDA version against `torch.version.cuda` and the device compute capability against `torch.cuda.get_arch_list()` with PTX awareness (a `compute_XX` PTX entry satisfies any device with compute capability ≥ XX); SHALL present each mismatch with detected versus expected values; SHALL offer a corrective install only after explicit operator consent with decline as the default; SHALL, upon consent, run the corrective install using the host-resolved wheel index and re-validate afterwards; SHALL record the decision and continue with a visible warning when consent is declined; and SHALL NOT install anything without consent.

#### Scenario: driver/torch CUDA mismatch is offered behind consent
- **WHEN** the wizard runs on a host with a CUDA 13.x driver and a torch built for CUDA 12.8
- **THEN** the wizard reports the mismatch between driver CUDA version and `torch.version.cuda`, offers a corrective install from the resolved index, and installs only after an explicit yes.

#### Scenario: declined consent continues without installing
- **WHEN** the operator declines the corrective install
- **THEN** nothing is installed, the mismatch and the decision are recorded, and the run continues with a visible warning.

#### Scenario: unsupported compute capability is detected
- **WHEN** the device compute capability (e.g. 8.7) appears in neither `torch.cuda.get_arch_list()` as `sm_87` nor as any `compute_XX` PTX entry with XX ≤ 8.7
- **THEN** the wizard reports the arch-list mismatch and offers the consented corrective install.

#### Scenario: PTX coverage counts as compatible
- **WHEN** the exact `sm_YY` SASS entry is absent but a `compute_XX` PTX entry with XX ≤ the device compute capability exists in `torch.cuda.get_arch_list()`
- **THEN** the wizard classifies the host as PTX-JIT-compatible, annotates it, and does not offer a corrective install for that reason alone.

#### Scenario: matched host proceeds unchanged
- **WHEN** driver CUDA version, `torch.version.cuda`, and arch-list coverage all agree
- **THEN** the wizard behaves exactly as before this change with no new prompts.

- [ ] 4.1 Implement a pure mismatch evaluator `(driver_cuda_version, torch_cuda_version, compute_capability, arch_list) -> {compatible | ptx_jit | mismatch(reasons)}`; unit-test exact SASS match, same-major PTX, cross-major PTX, and hard-mismatch cases.
- [ ] 4.2 Wire the evaluator into the first-run wizard: gather probes, render detected-versus-expected, and gate the corrective install behind an explicit consent prompt whose default is decline.
- [ ] 4.3 Implement the consented corrective install (invoke the installer with the resolved index or appropriate flavor) followed by re-validation of `torch.version.cuda` and arch coverage; abort cleanly with guidance if re-validation still fails.
- [ ] 4.4 Record the mismatch, consent decision, and outcome in wizard state and logs, including the continue-on-decline path with warning.
- [ ] 4.5 Add an end-to-end wizard test with simulated probes covering all five scenarios, asserting the corrective install runs with the expected `--index-url` on consent and that nothing runs on decline.

## 5. Documentation and operator visibility

### Requirement: Documented provisioning behavior
The repository SHALL document, in operator-facing docs: the ordered fallback table (keys, row order, terminal fallback) generated from or cross-checked against the implementation's single source of truth; the `--index-url` override and its precedence; the three `gpu-preflight` memory states and the never-refuse-on-unknown rule; and the unified-memory classification with its provenance semantics, including Jetson, AMD APU, and Apple Silicon notes. The installer help SHALL describe `--index-url` and the force flags.

#### Scenario: docs table matches the implementation
- **WHEN** the documentation cross-check test runs
- **THEN** the fallback table rendered in the docs matches the implementation's table row for row, in order.

#### Scenario: operators can discover the override
- **WHEN** an operator views the installer help
- **THEN** `--index-url`, its precedence over the table, and the unchanged force flags are documented.

- [ ] 5.1 Write the operator doc page covering the fallback table, `--index-url`, the three preflight memory states, unified-memory classification and provenance, and per-platform notes (Jetson, AMD APU, Apple Silicon); generate the table section from the implementation to prevent drift.
- [ ] 5.2 Add the docs cross-check test and update the installer help text.

## 6. Cross-host regression suite

### Requirement: No regression across supported host classes
The change SHALL NOT alter behavior for the dual-GPU x86_64 NVIDIA workstation default, ROCm hosts, XPU hosts, MPS hosts, or CPU-only hosts, except that MPS and AMD APU hosts gain correct unified-memory reporting; golden regression tests SHALL encode `describe_host()` output, resolved wheel index/flavor, and `gpu-preflight` decisions for each class; and the full existing suite SHALL pass unchanged.

#### Scenario: dual-GPU x86_64 NVIDIA workstation default preserved
- **WHEN** the golden fixtures for an x86_64 host with two discrete NVIDIA GPUs are replayed through `describe_host()`, the resolver, and `gpu-preflight`
- **THEN** `describe_host()` output is a schema-superset with identical pre-existing values, the resolver returns the cu128 index, and preflight decisions match the pre-change fixtures exactly.

#### Scenario: ROCm host unchanged
- **WHEN** the ROCm fixture is replayed
- **THEN** flavor selection, `describe_host()` accelerator reporting, and preflight decisions are identical to pre-change behavior and no CUDA index is consulted.

#### Scenario: XPU host unchanged
- **WHEN** the XPU fixture is replayed
- **THEN** flavor selection and preflight decisions are identical to pre-change behavior and no CUDA index is consulted.

#### Scenario: MPS host unchanged apart from unified reporting
- **WHEN** the Apple Silicon fixture is replayed
- **THEN** `--mps` flavor selection and wizard flow are unchanged, and memory is now reported as unified with system-pool figures instead of missing or zero VRAM.

#### Scenario: CPU-only host unchanged
- **WHEN** the CPU-only fixture is replayed
- **THEN** no accelerator is reported, the CPU index is selected, preflight passes without accelerator checks, and no CUDA table row is consulted.

- [ ] 6.1 Capture golden fixtures (describe_host JSON, resolver decision, preflight report) for x86_64 dual-GPU NVIDIA, ROCm, XPU, MPS, and CPU-only hosts, plus Jetson and AMD APU, from pre-change behavior where applicable.
- [ ] 6.2 Add a cross-host regression module replaying the fixtures through `describe_host()`, the resolver, and `gpu-preflight`, asserting the five scenarios above.
- [ ] 6.3 Run the full existing test suite and CI matrix, confirm zero regressions, and add the new regression module to CI.