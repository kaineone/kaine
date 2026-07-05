## ADDED Requirements

### Requirement: Cooperative pre-boot GPU headroom gate

The cycle SHALL, when `[gpu_preflight].enabled` is true, verify per-device GPU
headroom before initializing any module and before opening the bus, and SHALL
refuse to boot (a clean exit, before any resource is opened) when free VRAM on
any detected GPU is below `min_free_vram_gb` and cannot be reclaimed — unless the
operator sets the configured override environment variable. The check ships
disabled by default (operator-supervised first boot).

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

### Requirement: Reclaim is cooperative and never terminates a process

The gate SHALL reclaim VRAM only by evicting KAINE's own resident Ollama models
that are not needed by the organ, and SHALL NOT terminate any process — neither a
foreign GPU program nor a KAINE service (Ollama, Chatterbox, Speaches), which it
detects and preserves. The model the language organ is about to use SHALL be kept.

#### Scenario: Only non-organ models are evicted

- **WHEN** headroom is short and KAINE's Ollama has resident models including the
  organ's model and an unrelated model
- **THEN** the unrelated model is evicted and the organ's model is kept
- **AND** no process is terminated

#### Scenario: KAINE services are preserved and named

- **WHEN** headroom is short and a KAINE service (e.g. Chatterbox) is running
- **THEN** the service keeps running
- **AND** the operator message names it as a service to keep rather than close
