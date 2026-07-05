## MODIFIED Requirements

### Requirement: Lingua hot-swap mode is operator-configurable
`[hypnos.voice_alignment].hot_swap_mode` SHALL accept one of
`"manual"` (default), `"reload_endpoint"`, or `"restart_service"`, and on a
single-GPU host SHALL bracket the training step with an organ **unload** before
training and an organ **reload** after, so the trainer and the served organ do not
contend for the one device.

On adapter accept:
- `manual` — write a marker file
  `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` and log a line
  pointing the operator at the manual reload step. No service call.
- `reload_endpoint` — POST to a configured Unsloth Studio reload
  endpoint with the new adapter path (after the unload/reload bracket on
  single-GPU hosts).
- `restart_service` — invoke `systemctl --user restart` against a
  configured unit name, starting the organ with the accepted adapter applied.

When a second GPU has sufficient free VRAM to both serve and train, the unload
bracket SHALL be skipped (serve on one device, train on the other).

#### Scenario: Manual mode is the default
- **WHEN** an operator inspects shipped `config/kaine.toml`
- **THEN** `[hypnos.voice_alignment].hot_swap_mode = "manual"`

#### Scenario: Manual mode writes the marker
- **WHEN** an adapter is accepted under `hot_swap_mode = "manual"`
- **THEN** `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` exists
  and contains the path of the newest accepted adapter

#### Scenario: Single-GPU training brackets the organ with unload then reload
- **WHEN** the voice-alignment training step runs on a host with one usable GPU
- **THEN** the organ server is unloaded (its VRAM released and confirmed) before
  the trainer starts, and reloaded (confirmed answering) after the trainer ends —
  with the accepted adapter applied if one was accepted, or unchanged otherwise

#### Scenario: Multi-GPU host skips the unload bracket
- **WHEN** a second GPU has enough free VRAM to serve and train concurrently
- **THEN** the organ is not unloaded; the trainer runs on the second device

## ADDED Requirements

### Requirement: The trainer trains from the abliterated safetensors base
The trainer SHALL load its base weights from `[hypnos.voice_alignment].base_model_path`
pointing at the KAINE abliterated Qwen3.5-4B **safetensors** directory (not the
served GGUF), so the on-device QLoRA/bf16-LoRA step has real weights to attach a
LoRA to. The served (GGUF) form and the trained-from (safetensors) form SHALL
derive from one abliteration provenance.

#### Scenario: Enabled training requires a safetensors base path
- **WHEN** voice-alignment is enabled and operator-approved
- **THEN** `base_model_path` resolves to an existing abliterated safetensors
  directory, and the trainer loads from it rather than from the served GGUF

### Requirement: A failed training window leaves a working organ
The system SHALL guarantee that a failure during the training window — unload,
train, adapter application, or reload — leaves the entity with a working organ on
wake. On any bracket-step failure or training timeout, the cycle SHALL log the
failure, reload the pre-training organ artifact (retained), and complete the
remaining sleep phases; it SHALL NOT leave the organ unloaded into the awake
period.

#### Scenario: Reload failure rolls back to the prior organ
- **WHEN** applying the new adapter or reloading the organ fails after training
- **THEN** the pre-training organ artifact is reloaded and confirmed answering, the
  failure is logged, and the sleep cycle's other phases still complete

#### Scenario: Training timeout aborts and restores
- **WHEN** the trainer subprocess exceeds its wall-clock bound
- **THEN** training is aborted and the organ is reloaded unchanged before wake
