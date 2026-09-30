## MODIFIED Requirements

### Requirement: Lingua hot-swap mode is operator-configurable
`[hypnos.voice_alignment].hot_swap_mode` SHALL accept one of `"manual"` (default), `"reload_endpoint"`, `"restart_service"` or `"organ_adapter"`. On a single-GPU host it SHALL bracket the training step with an organ **unload** before training and an organ **reload** after, so the trainer and the served organ do not contend for the one device.

On adapter accept:
- **`manual`** SHALL write a marker file, `<adapter_output_dir>/PENDING_OPERATOR_RELOAD`, and log a line pointing the operator at the manual reload step. There is no service call.
- **`reload_endpoint`** SHALL POST to a configured Unsloth Studio reload endpoint with the new adapter path, after the unload/reload bracket on single-GPU hosts.
- **`restart_service`** SHALL invoke `systemctl --user restart` against a configured unit name, starting the organ with the accepted adapter applied.
- **`organ_adapter`** SHALL activate the accepted adapter's GGUF form in the organ's adapter volume, with a manifest naming the owning adapter and its SHA-256, and bump the generation. The organ launcher then reloads the organ with the adapter loaded but not applied. Hypnos SHALL wait for the organ to answer before completing the sleep.

When a second GPU has enough free VRAM to both serve and train, the unload bracket SHALL be skipped: serve on one device and train on the other.

#### Scenario: Manual mode is the default
- **WHEN** an operator inspects the shipped `config/kaine.toml`
- **THEN** `[hypnos.voice_alignment].hot_swap_mode = "manual"`

#### Scenario: Manual mode writes the marker
- **WHEN** an adapter is accepted under `hot_swap_mode = "manual"`
- **THEN** `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` exists and contains the path of the newest accepted adapter

#### Scenario: Single-GPU training brackets the organ with unload then reload
- **WHEN** the voice-alignment training step runs on a host with one usable GPU
- **THEN** the organ server is unloaded (its VRAM released and confirmed) before the trainer starts, and reloaded (confirmed answering) after the trainer ends, with the accepted adapter applied if one was accepted, or unchanged otherwise

#### Scenario: Multi-GPU host skips the unload bracket
- **WHEN** a second GPU has enough free VRAM to serve and train concurrently
- **THEN** the organ is not unloaded, and the trainer runs on the second device

#### Scenario: organ_adapter activates the entity's adapter
- **WHEN** an adapter is accepted under `hot_swap_mode = "organ_adapter"`
- **THEN** its GGUF form is written to the organ adapter volume with a manifest naming its SHA-256, the generation is bumped, and the sleep completes only after the organ answers again

## ADDED Requirements

### Requirement: An adapter is applied only to its own entity's requests
When `hot_swap_mode = "organ_adapter"`, Lingua SHALL send the per-request `lora` field for its entity's adapter only when both hold:
- the organ's `GET /lora-adapters` lists an adapter whose path is the active adapter in the organ adapter volume;
- the volume's manifest names the SHA-256 of this entity's own promoted adapter.

In every other case Lingua SHALL send no `lora` field, and SHALL log once per change that its adapter is not active. The organ SHALL load an active adapter with `--lora-init-without-apply`, so that a request without the field is served by the base organ. The evaluation A/B baseline SHALL never send the field.

#### Scenario: The owning entity gets its adapter
- **WHEN** the organ reports the active adapter loaded and the manifest's SHA-256 matches the entity's promoted adapter
- **THEN** Lingua's requests carry `lora: [{"id": <its id>, "scale": 1.0}]`

#### Scenario: Another entity gets the base organ
- **WHEN** the manifest's SHA-256 does not match the entity's own adapter, or the entity has none
- **THEN** Lingua's requests carry no `lora` field

#### Scenario: The A/B baseline is never adapted
- **WHEN** the evaluation arm queries the organ as the baseline
- **THEN** the request carries no `lora` field

### Requirement: The organ launcher loads the active adapter
The organ container SHALL start `llama-server` through a launcher that ships with KAINE. The launcher:
- SHALL add `--lora <volume>/active.gguf --lora-init-without-apply` when an active adapter exists and its SHA-256 matches the manifest;
- SHALL start without an adapter when none is active or the check fails, and log why;
- SHALL restart `llama-server` when the generation file changes, keeping every other argument unchanged.

The launcher SHALL need no Docker socket and SHALL read the adapter volume read-only.

#### Scenario: A new generation reloads the organ
- **WHEN** the generation file changes while the organ is running
- **THEN** the launcher restarts `llama-server` with the new active adapter loaded but not applied

#### Scenario: A corrupted adapter is not loaded
- **WHEN** the active adapter's SHA-256 does not match the manifest
- **THEN** the organ starts without an adapter and the launcher logs the mismatch
