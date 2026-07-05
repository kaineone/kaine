## ADDED Requirements

### Requirement: select_device accepts indexed CUDA strings
`kaine.hardware.select_device` SHALL accept any of `cuda:0`,
`cuda:1`, … `cuda:N` as the `preferred` argument, in addition to
the existing `cuda` / `mps` / `cpu` / `auto` / `None` values. When
`cuda:N` is passed and torch reports at least N+1 CUDA devices,
the call SHALL return the exact string. When `cuda:N` is passed
but torch does not see device N, the call SHALL raise `ValueError`.

#### Scenario: Indexed device honored when present
- **WHEN** torch reports 2 CUDA devices and `select_device("cuda:1")`
  is called
- **THEN** the return value is `"cuda:1"`

#### Scenario: Missing index raises
- **WHEN** torch reports 1 CUDA device and `select_device("cuda:1")`
  is called
- **THEN** ValueError is raised

### Requirement: resolve_device falls back with warning
The `resolve_device(preferred, *, fallback="cuda:0")` helper SHALL
never raise on a missing CUDA index. Instead it SHALL log a warning
and return the `fallback` device (or `cpu` if the fallback itself
isn't available). This is the helper module factories call so a
stale operator config doesn't crash the boot.

#### Scenario: Missing index falls back to cuda:0
- **WHEN** torch reports 1 CUDA device and `resolve_device("cuda:1")`
  is called
- **THEN** the return value is `"cuda:0"` and a warning was logged

#### Scenario: No CUDA at all falls back to cpu
- **WHEN** torch reports zero CUDA devices and `resolve_device("cuda:1")`
  is called
- **THEN** the return value is `"cpu"` and a warning was logged

### Requirement: available_cuda_devices enumerates present devices
`kaine.hardware.available_cuda_devices()` SHALL return a list of
indexed CUDA strings for every present device, e.g.
`["cuda:0", "cuda:1"]`. On a host without CUDA the list SHALL be
empty.

#### Scenario: Two GPUs enumerated
- **WHEN** torch reports 2 CUDA devices
- **THEN** the return value is `["cuda:0", "cuda:1"]`

### Requirement: tune_cpu_threads bounds the CPU pool
`kaine.hardware.tune_cpu_threads()` SHALL set
`torch.set_num_threads` to at most `cpu_count // 2` (minimum 1)
so concurrent CPU-bound modules don't oversubscribe a many-core
host. The function SHALL be safe to call before torch is fully
initialized.

#### Scenario: Thread cap applied
- **WHEN** the host has 32 logical CPUs and `tune_cpu_threads()` runs
- **THEN** `torch.get_num_threads()` returns 16 or fewer

### Requirement: describe_host reports per-device VRAM
`kaine.hardware.describe_host()` SHALL include a `cuda_devices`
field — a list of dicts each with `index`, `name`, `total_vram_gb`,
and `free_vram_gb` — when CUDA is present.

#### Scenario: Two-GPU host enumerated
- **WHEN** the host has 2 CUDA devices
- **THEN** `describe_host()["cuda_devices"]` has length 2 and each
  entry has the documented keys
