## ADDED Requirements

### Requirement: Accelerator/runtime mismatch detection with consented corrective install
The first-run wizard SHALL detect an accelerator/runtime mismatch on the current host before finalizing its accelerator configuration. Detection SHALL compare the probed driver's CUDA version against `torch.version.cuda`, and SHALL compare each detected device's compute capability against `torch.cuda.get_arch_list()` in a PTX-aware way: a wheel that carries PTX for an architecture at or below the device's compute capability can JIT-compile for that device and SHALL NOT be reported as a mismatch. If either side of a comparison cannot be determined, the wizard SHALL report the check as unknown rather than claiming a mismatch. On a detected mismatch the wizard SHALL explain the problem in operator terms, naming the `no kernel image is available for execution on the device` failure it prevents, and SHALL offer a consented corrective reinstall of the accelerator stack from the correct index for the probed host (honoring any operator `--index-url` override). The wizard SHALL NOT install anything without an explicit operator yes, SHALL let the wizard finish when the offer is declined, and SHALL skip this check entirely on hosts with no detected accelerator.

#### Scenario: Detected mismatch is offered and the operator accepts
- **WHEN** the wizard runs on a host where the installed wheel disagrees with the probed host, for example an aarch64 host whose driver reports CUDA 13.x and whose device is sm_87, while the installed wheel reports `torch.version.cuda` 12.8 and `torch.cuda.get_arch_list()` covers only sm_90/sm_100 with no PTX entry at or below sm_87
- **THEN** the wizard explains in operator terms that the installed wheel cannot run kernels on this GPU and names the `no kernel image is available for execution on the device` failure it prevents, offers to reinstall the accelerator stack from the correct index for the probed host, and, because the operator explicitly accepts, performs the corrective reinstall from that index and continues the wizard with the corrected stack.

#### Scenario: Detected mismatch is offered and the operator declines
- **WHEN** the wizard detects an accelerator/runtime mismatch and presents its explanation and corrective-install offer, and the operator explicitly declines
- **THEN** the wizard performs no install and changes no packages, records that the corrective offer was declined, and still finishes the wizard successfully with the existing accelerator stack left in place.

#### Scenario: PTX-compatible wheel is not reported as a mismatch
- **WHEN** the device's compute capability has no exact SASS entry in `torch.cuda.get_arch_list()` but the wheel ships PTX for a lower architecture, for example a sm_120 device with an arch list ending in `compute_90`/`sm_90+PTX`
- **THEN** the wizard classifies the installed wheel as JIT-capable on this device, does not report a mismatch, does not offer a corrective reinstall, and finishes normally.

#### Scenario: Matching x86_64 CUDA workstation reports no mismatch
- **WHEN** the wizard runs on the dual-GPU x86_64 NVIDIA workstation where the driver's CUDA version matches `torch.version.cuda` and both GPUs' compute capabilities appear as SASS entries in `torch.cuda.get_arch_list()`
- **THEN** the wizard reports no mismatch, offers no corrective install, and completes with the existing accelerator stack unchanged.

#### Scenario: CPU-only host skips the mismatch check
- **WHEN** the wizard runs on a host with no detected accelerator (CPU-only)
- **THEN** the wizard skips the accelerator/runtime mismatch check entirely, does not query CUDA driver or `torch.cuda` runtime information for the comparison, reports the check as skipped or not applicable, and finishes normally without offering any corrective install.