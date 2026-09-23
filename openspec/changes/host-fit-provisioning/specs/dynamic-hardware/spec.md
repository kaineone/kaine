## ADDED Requirements

### Requirement: Wheel-index resolution satisfies the project torch floor
The wheel-index resolver SHALL only select an index whose newest published torch satisfies the torch requirement in `pyproject.toml`. When the decision-table row's index cannot satisfy it, the resolver SHALL select the newest index that can and that the host driver supports, and when none exists SHALL select the CPU index with a warning naming the floor and the driver version.

#### Scenario: CUDA 12.8 driver with a 2.14 floor
- **WHEN** an x86_64 host reports driver CUDA 12.8, the floor is `torch>=2.14.0`, and cu128's newest torch is 2.11.0
- **THEN** the resolver selects cu126 and logs why

#### Scenario: Driver too old for any index carrying the floor
- **WHEN** a host's driver supports only indexes whose newest torch is below the floor
- **THEN** the resolver selects CPU and the warning names the floor and the driver version

### Requirement: ROCm index follows the torch floor
The ROCm install flavor SHALL use the newest ROCm wheel index that carries a torch satisfying the project floor, and SHALL warn that hosts on older ROCm stacks cannot use it.

#### Scenario: ROCm install with a 2.14 floor
- **WHEN** the installer runs with `--rocm` and the floor is `torch>=2.14.0`
- **THEN** pip receives the rocm7.2 index and the output notes the ROCm 7.2 requirement

### Requirement: JetPack 7 Jetson hosts use the GPU wheels
A unified-memory aarch64 host whose driver reports CUDA 13.0 or newer SHALL resolve to the newest `cu13x` index carrying the floor, with a warning that Orin-class GPUs run compatible rather than native kernels.

#### Scenario: Orin Nano on JetPack 7.2
- **WHEN** the resolver probes aarch64, unified memory and driver CUDA 13.2
- **THEN** it selects a cu13x index and emits the compatibility warning instead of the CPU index
