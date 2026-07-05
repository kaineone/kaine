## MODIFIED Requirements

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
