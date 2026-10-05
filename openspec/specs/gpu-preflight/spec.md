# gpu-preflight Specification

## Purpose
The gpu-preflight capability is a cooperative pre-boot gate that checks per-device GPU headroom before the cycle opens any resource, refuses to boot when free VRAM is below the configured threshold and cannot be reclaimed, and never terminates another process to reclaim memory.

## Requirements

### Requirement: Cooperative pre-boot GPU headroom gate

The cycle SHALL, when `[gpu_preflight].enabled` is true, verify per-device GPU
headroom before initializing any module and before opening the bus, and SHALL
refuse to boot (a clean exit, before any resource is opened) when free memory on
any detected GPU is below `min_free_vram_gb` and cannot be reclaimed — unless the
operator sets the configured override environment variable. The check ships
disabled by default (operator-supervised first boot).

For every detected GPU the gate SHALL classify memory into exactly one of three
states — `known-discrete`, `known-unified`, or `unknown` — derived from the
hardware probe (the host description reported by `describe_host()`), and SHALL
record the state, the measured figure and its provenance in the gate report:

- **known-discrete** — the accelerator exposes a dedicated memory pool whose free
  capacity the host can read (e.g. NVML free VRAM on a discrete card). The gate
  SHALL apply `min_free_vram_gb` to that pool; behaviour, operator messages and
  exit codes are unchanged from the pre-existing gate.
- **known-unified** — the accelerator draws on memory shared with the system
  (integrated GPUs such as NVIDIA Tegra/Jetson, AMD APUs, Apple Silicon), so no
  separate VRAM pool exists. The gate SHALL apply the same `min_free_vram_gb`
  threshold to the available system memory of the shared pool, because memory the
  accelerator consumes is memory unavailable to the host.
- **unknown** — the free capacity of the relevant pool cannot be determined (no
  usable probe, the driver reports "Not Supported", or the figure is otherwise
  unknowable). The gate SHALL pass and SHALL annotate its report and operator
  output with the unknown state and the reason no figure could be measured;
  unknowable memory alone must never refuse boot.

Only a measured shortfall in a known state (`known-discrete` or
`known-unified`) may trigger refusal. The gate SHALL NOT refuse boot, and SHALL
NOT require the override environment variable, on the basis of unknown memory
alone. The gate report SHALL remain JSON-serializable in all three states.

#### Scenario: Ample headroom passes

- **WHEN** every detected GPU has at least `min_free_vram_gb` free
- **THEN** the gate passes and boot proceeds

#### Scenario: Short headroom refuses to boot

- **WHEN** a detected GPU is below `min_free_vram_gb` after reclamation
- **AND** the override environment variable is not set
- **THEN** the cycle refuses to boot with a non-zero exit before the bus or any
  module is opened
- **AND** the operator message lists the per-device shortfall and the GPU memory
  consumers to free

#### Scenario: Operator override boots anyway

- **WHEN** headroom is short
- **AND** the override environment variable is set to `1`
- **THEN** the gate reports `overridden` and boot proceeds

#### Scenario: Unified-memory host with ample shared memory passes

- **WHEN** a detected GPU is classified as unified memory (no separate VRAM pool)
- **AND** available system memory is at least `min_free_vram_gb`
- **THEN** the gate passes and boot proceeds
- **AND** the gate report records the state `known-unified` with the available
  system-memory figure and its provenance

#### Scenario: Unified-memory host short on shared memory refuses to boot

- **WHEN** a detected GPU is classified as unified memory
- **AND** available system memory is below `min_free_vram_gb` after reclamation
- **AND** the override environment variable is not set
- **THEN** the cycle refuses to boot with a non-zero exit before the bus or any
  module is opened
- **AND** the operator message states that the threshold was applied to available
  system memory and lists the shortfall and the memory consumers to free

#### Scenario: Unified-memory shortfall honours the operator override

- **WHEN** a unified-memory GPU is short on available system memory
- **AND** the override environment variable is set to `1`
- **THEN** the gate reports `overridden` and boot proceeds

#### Scenario: Unknowable memory passes with annotation

- **WHEN** the gate cannot determine free memory for a detected GPU (no usable
  probe, or the driver reports "Not Supported")
- **THEN** the gate passes and boot proceeds
- **AND** the gate report and operator output annotate that GPU's memory state as
  `unknown`, including the reason no figure could be measured
- **AND** the unknown state alone never produces a non-zero exit and never
  requires the override environment variable

#### Scenario: Mixed host enforces known devices and annotates unknown ones

- **WHEN** one detected GPU has known-discrete memory below `min_free_vram_gb`
  after reclamation and another detected GPU has unknown memory
- **AND** the override environment variable is not set
- **THEN** the cycle refuses to boot because of the known-short device
- **AND** the operator message annotates the unknown-memory device as unverified
  rather than reporting it as short

### Requirement: Reclaim is cooperative and never terminates a process

The gate SHALL reclaim VRAM only by evicting the inference backend's own resident
models that are not needed by the organ, and SHALL NOT terminate any process —
neither a foreign GPU program nor a KAINE service (the model server, Chatterbox,
Speaches), which it detects and preserves. The model the language organ is about
to use SHALL be kept. When the configured backend serves a **single resident
model** (as Unsloth Studio / `llama-server` does — that resident model being the
organ itself), there is no idle model to evict and reclamation SHALL be
**report-only**: the gate still measures per-device headroom, still names GPU
memory consumers, still preserves KAINE services, and still terminates nothing.

#### Scenario: Only non-organ models are evicted when the backend holds several

- **WHEN** headroom is short and the backend has resident models including the
  organ's model and an unrelated model
- **THEN** the unrelated model is evicted and the organ's model is kept
- **AND** no process is terminated

#### Scenario: Single-resident backend reclaims report-only

- **WHEN** headroom is short and the backend serves only the organ's model
- **THEN** there is no idle model to evict and the gate reports the per-device
  shortfall and the GPU memory consumers to free
- **AND** no process is terminated and no service is stopped

#### Scenario: KAINE services are preserved and named

- **WHEN** headroom is short and a KAINE service (e.g. Chatterbox, the model
  server) is running
- **THEN** the service keeps running
- **AND** the operator message names it as a service to keep rather than close

### Requirement: The gate names shared services and never asks to close them
When a process holding memory on a device the cycle needs belongs to a service marked `[services.<name>].shared = true`, the gate SHALL name that service as shared with the operator's other applications. It SHALL suggest a placement that avoids the device (another allowed device, a lighter backend rung, or CPU) instead of asking the operator to close it. The gate SHALL still never terminate any process.

#### Scenario: A shared server fills the vision device
- **WHEN** a shared text-to-speech server leaves the vision device below the free-memory minimum
- **THEN** the block message names the shared service
- **AND** it suggests an alternative placement
- **AND** it does not ask the operator to close the service

### Requirement: The consumer list says when it cannot see the host
When the gate runs where host processes are not visible, such as inside a container's process namespace, it SHALL say that its consumer list is limited to the container. It SHALL report the device's used memory. It SHALL NOT attribute memory held outside the container to a process inside it.

#### Scenario: Gate inside a container
- **WHEN** a host process holds most of a device and the gate runs in a container
- **THEN** the message states that host processes are not visible from the container
- **AND** it reports the device's used and free memory
