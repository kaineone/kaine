## ADDED Requirements

### Requirement: The wizard inventories the host's usable hardware
The wizard SHALL list every compute device that the host probe recognises: CUDA, ROCm, XPU, MPS, a unified-memory accelerator, and the CPU. Each device SHALL be listed with its total and free memory, and with the processes currently holding it where they are visible. The wizard SHALL also list the CPU cores and the system memory. It SHALL NOT assume any particular device count, vendor or memory size.

#### Scenario: A host with one non-NVIDIA accelerator
- **WHEN** the probe reports a single ROCm or XPU device
- **THEN** the wizard lists that device with its memory
- **AND** it does not report "no CUDA GPUs detected" as if the host had no accelerator

#### Scenario: A device already in use
- **WHEN** another process holds memory on a listed device
- **THEN** the wizard shows that process and the memory it holds beside the device

### Requirement: The operator chooses the hardware KAINE may use
The wizard SHALL ask which of the listed devices KAINE may use, and how many CPU threads it may use. It SHALL record the answer in `[hardware]` of the operator config. Device assignments SHALL be proposed only from the allowed set. Each proposal SHALL be checked against the device's free memory, and against measured footprints when a calibrated footprint catalogue exists. A proposal that does not fit SHALL say so and offer the alternatives: another allowed device, a lighter backend rung, or CPU.

#### Scenario: A GPU kept for other work
- **WHEN** the operator leaves a GPU out of the allowed set
- **THEN** no proposed assignment uses that GPU

#### Scenario: The proposed device lacks free memory
- **WHEN** the device proposed for a component has less free memory than the component needs
- **THEN** the wizard says so
- **AND** it offers the alternatives instead of writing the assignment silently

### Requirement: One device map drives the cycle and its services
The wizard SHALL write the device map once, to the operator config. The compose GPU variables and the native service launchers SHALL be generated from that map, so the cycle and the external services cannot disagree about which device serves which role.

#### Scenario: Compose installs
- **WHEN** the operator completes the hardware step on a compose install
- **THEN** the compose GPU variables are written from the same device map as the cycle's device keys

### Requirement: Shared services are declared, not owned
The wizard SHALL ask, for each external service it detects, whether the service is shared with the operator's other applications. It SHALL record the answer as `[services.<name>].shared`. KAINE SHALL NOT stop, restart or evict a shared service.

#### Scenario: A shared speech server
- **WHEN** the operator marks the text-to-speech server as shared
- **THEN** no KAINE setup step, pre-boot step or cycle step stops or restarts it

### Requirement: The operator chooses where growing data lives
The wizard SHALL list the mounted filesystems with their free space and ask for a data root. When a filesystem other than the system drive has more free space, the wizard SHALL recommend it. It SHALL refuse a root that lacks the configured minimum free space. It SHALL record the choice as `[storage].data_root`. On a compose install it SHALL write a local, gitignored override that binds the growing volumes under the data root. Relocating an existing data root SHALL copy, verify and only then switch, leaving the old copy for the operator to remove.

#### Scenario: A small system drive and a large data drive
- **WHEN** the system drive has less free space than a mounted data drive
- **THEN** the wizard recommends a data root on the data drive
- **AND** it writes the choice only after the operator confirms

#### Scenario: Relocation keeps the original
- **WHEN** the operator moves an existing data root
- **THEN** the data is copied and verified before the configuration points at the new root
- **AND** the original is not deleted
