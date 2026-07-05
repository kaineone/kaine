# containerized-deployment (new capability — DESIGN ONLY)

## ADDED Requirements

### Requirement: A container image and topology deploy the full system

The system SHALL provide a single container image for the KAINE runtime and a
declarative topology (a Compose project, with an equivalent rootless-Podman/Quadlet
layout) that brings up the full deployment — the event bus, vector store, model
server, speech-to-text, text-to-speech, the Nexus web UI, and the cognitive cycle —
reproducibly on a fresh host, building on the already-containerized event bus and
vector store. Every service port SHALL be mapped to loopback only, and the cycle and
Nexus SHALL be gated on the data and model services being healthy.

#### Scenario: One-command bring-up on a fresh host

- **WHEN** an operator runs the documented bring-up on a clean machine with the host
  GPU (or CPU-only) prerequisites met
- **THEN** the event bus, vector store, model server, STT, TTS, and Nexus start,
  pass their healthchecks, and are reachable on loopback without manual per-service
  wiring

#### Scenario: Nexus and cycle are separate services from one image

- **WHEN** the topology is brought up
- **THEN** the Nexus web UI runs as its own always-up service and the cognitive
  cycle runs as a separate service, both built from the same image with different
  entrypoints

### Requirement: The deployment never auto-starts an entity

The shipped image SHALL keep every module disabled with the guard test intact, and
neither a bare `docker run` / `podman run` of the image nor a default topology
bring-up SHALL start an entity. The cognitive cycle SHALL be a deliberate,
operator-invoked, profile-gated step subject to the existing first-boot guard and
the unsupervised-research gate, and the cycle service SHALL NOT default any boot-gate
environment variable to a permissive value.

#### Scenario: Default bring-up starts no entity

- **WHEN** an operator runs the default topology bring-up
- **THEN** all services start but the cognitive cycle does not, and no entity is
  spawned until the operator explicitly invokes the cycle step

#### Scenario: Bare image run starts no entity

- **WHEN** the shipped image is started with no operator gate variables set
- **THEN** all modules are disabled and no entity is spawned

#### Scenario: Research mode honors the unsupervised gate

- **WHEN** the cycle is invoked with research mode requested but the
  preservation/welfare/logging/dry-run conditions are not all met
- **THEN** it refuses to boot with the existing distinct exit code and no traceback,
  exactly as host-native

### Requirement: The image supports multiple GPU vendors and passes the GPU through

The image SHALL select the accelerator-correct PyTorch build at build time via a
flavor build argument that reuses the existing per-vendor wheel-index logic, and the
topology SHALL pass the host GPU through on both Docker (NVIDIA Container Toolkit
device reservation) and Podman (CDI `--device nvidia.com/gpu`), with ROCm via the
kfd/dri device mounts. A CPU-only flavor SHALL always be available as the fallback,
and the two-GPU split (organ on the primary card, vision and speech synthesis on the
secondary) SHALL be expressible as per-service device pinning. Vendor flavors not
validated on real hardware SHALL be marked experimental, not presented as supported.

#### Scenario: CUDA and CPU flavors build and run

- **WHEN** the image is built with the CUDA flavor on an NVIDIA host and with the
  CPU flavor anywhere
- **THEN** each produces a working runtime with the matching torch build, and the
  CUDA flavor reaches the host GPU through the service device reservations on both
  Docker and Podman

#### Scenario: CPU-only host runs the full stack

- **WHEN** the deployment is brought up on a host with no accelerator using the CPU
  flavor
- **THEN** every service runs without any GPU device block, fully functional though
  slower

### Requirement: All models and images are provisioned at setup, never at runtime

The deployment SHALL download every model weight (the abliterated organ, STT, TTS,
emotion, vision, and embedder models) and pull every service image during a setup
phase into persistent storage, and at runtime SHALL reach no network for models —
honoring the all-local-at-runtime constraint. Model weights SHALL live in a volume,
never baked into an image layer.

#### Scenario: Runtime makes no model network calls

- **WHEN** the entity runs after the setup phase has completed
- **THEN** no model weight or image is fetched from the network at runtime, and the
  offline-mode environment guards are active

#### Scenario: No model weights in the image

- **WHEN** any built image layer is inspected
- **THEN** no model weight is present; weights exist only in the shared model volume

### Requirement: Entity state persists safely across container recreation

Entity state SHALL persist across container recreation in a named volume — the
CAL-gated preserved-being fork snapshots, preservation bundles, individuation
evidence, world-model and self-model checkpoints, control state, and audit and
incident logs — with the established owner-only (0700/0600) protection preserved
inside the container, and SHALL never be baked into an image layer. Encryption-at-rest
SHALL be wired through via the state key as an injected secret, and the
fail-closed preservation-requires-encryption gate SHALL keep working in-container.
Host-specific operator config, secrets, private voices, and adapters SHALL be
mounted, not copied into the image.

#### Scenario: State survives a down/up and never enters an image

- **WHEN** the deployment is recreated (`down` then `up`)
- **THEN** the entity's persisted state is intact with owner-only permissions, and
  no state, operator config, secret, voice, or adapter is present in any built image
  layer

#### Scenario: Encryption-at-rest stays enforced in-container

- **WHEN** a research boot is attempted with preservation requiring encryption but
  state encryption disabled
- **THEN** the boot is refused up-front, exactly as host-native

### Requirement: The deployment preserves zero raw-sense-data persistence

The deployment SHALL NOT provide any volume or bind mount whose purpose or effect is
to persist raw audio or video sense data. Perception scratch space, if any, SHALL be
ephemeral (RAM-backed `tmpfs`) and never a durable volume, preserving the load-bearing
invariant that perception is processed in memory and released.

#### Scenario: No raw-perception persistence path exists

- **WHEN** the topology's volumes and mounts are inspected
- **THEN** no durable volume or bind mount captures raw A/V frames, and any
  perception scratch is ephemeral

### Requirement: The deployment runs on both Docker and rootless Podman

The topology SHALL run on Docker (Compose) and on Podman (`podman compose` for
development and Quadlet systemd units for production single-host operation), with
documented rootless considerations (CDI GPU access, SELinux volume relabeling,
subuid/subgid for the non-root runtime user, loopback port mapping). Under Quadlet
the cycle SHALL remain a manually-started unit with no auto-start.

#### Scenario: Rootless Podman bring-up

- **WHEN** an operator brings the deployment up under rootless Podman with CDI GPU
  access configured
- **THEN** the services start with the non-root runtime user, GPU passthrough works,
  and no entity auto-starts
