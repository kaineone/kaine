# organ-provisioning Specification

## Purpose
TBD - created by archiving change published-organ-install. Update Purpose after archive.
## Requirements
### Requirement: The shipped default resolves to the published KAINE organ

The shipped configuration SHALL set the language organ to the published KAINE
abliterated organ, and the evaluation A/B baseline SHALL derive from that same value
(fail-closed on explicit mismatch, unchanged). Repointing the organ SHALL require no
edit to the evaluation section.

#### Scenario: Shipped config points at the published organ

- **WHEN** an operator inspects shipped `config/kaine.toml`
- **THEN** `[lingua].model_id` is the published KAINE organ (`kaineone/...`) and
  `[evaluation].chat_model_id` is unset (it derives from `[lingua].model_id`)

#### Scenario: The first-boot guard is unaffected

- **WHEN** the all-modules-off first-boot guard runs against the shipped config
- **THEN** it still passes (the guard does not constrain `model_id`, and every module
  toggle remains off)

### Requirement: Fresh installs offer a consented organ download when the organ is needed

The installer/wizard SHALL offer to download the published organ weights, and SHALL
do so only when the language organ is enabled and only on explicit operator consent.
A declined offer SHALL print acquisition guidance and download nothing. The download
SHALL be a real operation reporting real success or failure — never a faked or no-op
"installed" result.

#### Scenario: Lingua enabled and consent given

- **WHEN** lingua is enabled and the operator consents to the download
- **THEN** a real download of the published weights runs and reports its actual
  success or failure

#### Scenario: Offer declined

- **WHEN** the operator declines the download
- **THEN** acquisition guidance is printed and no weights are downloaded

#### Scenario: Organ not needed

- **WHEN** the install does not enable lingua
- **THEN** no organ-download step is offered

### Requirement: Organ acquisition is hardware-aware

The download path SHALL be selected from the detected GPU backend, reusing the
existing backend detection: an NVIDIA host SHALL use the Unsloth Studio direction and
an AMD-only host SHALL use the unsloth-core direction. When no supported accelerator
toolchain is present the wizard SHALL print guidance rather than installing silently.

#### Scenario: NVIDIA host

- **WHEN** the detected backend is CUDA/NVIDIA
- **THEN** the organ is acquired via the Unsloth Studio path

#### Scenario: AMD-only host

- **WHEN** the detected backend is ROCm/AMD
- **THEN** the organ is acquired via the unsloth-core path

### Requirement: The downloaded format matches the host's role

The download SHALL fetch the GGUF (served by the OpenAI-compatible model server) by
default, and SHALL additionally fetch the safetensors base when on-device
voice-alignment (Stage-2) training is enabled, because the trainer requires it as its
base model. A serve-only host SHALL NOT download the safetensors.

#### Scenario: Serve-only host

- **WHEN** lingua is enabled and voice-alignment Stage-2 training is disabled
- **THEN** only the GGUF is downloaded

#### Scenario: Training-enabled host

- **WHEN** on-device voice-alignment Stage-2 training is enabled
- **THEN** both the GGUF and the safetensors base are downloaded

### Requirement: The model server is launched and supervised as a service

The system SHALL launch the OpenAI-compatible model server as a consent-gated service
(promoted from guide-only to a bootstrap command, mirroring the other launched
services), so a fresh install reaches a running organ without a manual server start.
The bootstrap SHALL locate the hardware-appropriate server binary (the Unsloth Studio
server on NVIDIA, the unsloth-core build on AMD), launch it against the downloaded
GGUF under the exact `[lingua].model_id` alias with chain-of-thought suppressed on the
configured port, and supervise the process so a crash is restarted (a `systemd --user`
restart-on-failure unit where available, otherwise a supervised background process
with a pidfile). It SHALL provide start, status, and stop, and SHALL NOT silently
install the multi-GB server toolchain — if the binary is absent it SHALL print
guidance and fail.

#### Scenario: Turnkey launch on consent

- **WHEN** lingua is enabled, the organ is downloaded, and the operator consents to
  start the server
- **THEN** the bootstrap launches the server against the GGUF under the configured
  alias and the organ becomes reachable without a manual server start

#### Scenario: Server binary absent

- **WHEN** the hardware-appropriate server binary is not installed
- **THEN** the bootstrap prints install guidance and fails rather than silently
  installing the toolchain

#### Scenario: Crash is restarted

- **WHEN** the launched model server process exits unexpectedly
- **THEN** the supervisor restarts it (systemd-user restart-on-failure or the
  background-process supervisor)

### Requirement: The served organ name is verified against the configuration

The system SHALL verify that the running model server lists the organ under the exact
alias configured in `[lingua].model_id` before declaring the organ ready, and SHALL
report an actionable mismatch rather than letting the cycle fail with a server 404 on
its first language call. The launched server's port SHALL be treated as a KAINE-owned
service by the GPU pre-boot headroom gate and SHALL never be terminated as a foreign
consumer.

#### Scenario: Served alias matches

- **WHEN** the model server lists a model whose name equals `[lingua].model_id`
- **THEN** the organ is reported ready

#### Scenario: Served alias mismatch

- **WHEN** the server is up but does not list a model matching `[lingua].model_id`
- **THEN** a "served name ≠ configured name" mismatch is reported and the organ is not
  declared ready

#### Scenario: Pre-boot gate preserves the server

- **WHEN** the GPU pre-boot headroom gate inspects GPU consumers
- **THEN** the launched model server is recognized as a KAINE-owned service and is not
  terminated

### Requirement: The published organ is recorded as a research covariate

The system SHALL record the published organ's repository id (and its resolved
revision when available) in the research run manifest, so a run's perceptual organ is
part of the reproducible experimental record.

#### Scenario: Run records the published organ

- **WHEN** a research run starts with the published organ configured
- **THEN** the run manifest records the published organ repo id as a model covariate

