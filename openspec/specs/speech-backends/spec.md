# speech-backends Specification

## Purpose
This capability lets the audition and vocal modules run on torch-free speech backends (sherpa-onnx) for edge and Termux hosts. Speech events disclose which backend produced them, speech models are fetched only with the operator's consent and verified before loading, and the health surface probes the backend actually selected.

## Requirements

### Requirement: Audition and Vocal select a torch-free speech backend

The audition module SHALL select its speech recogniser with `[audition].backend` (`"speaches"`, the default, or `"sherpa_onnx"`), and the vocal module SHALL select its synthesiser with `[vocal].backend` (`"chatterbox"`, the default, or `"sherpa_onnx"`). The `"sherpa_onnx"` backends SHALL run Moonshine and Kokoro through sherpa-onnx behind the modules' existing client interfaces, SHALL import no torch, and SHALL run inference off the event loop. An unknown backend SHALL be a configuration error.

#### Scenario: Defaults are unchanged
- **WHEN** neither key is set
- **THEN** the audition module uses Speaches and the vocal module uses Chatterbox, as before

#### Scenario: Round trip on the sherpa backends
- **WHEN** both organs select `"sherpa_onnx"` with their models installed, and the vocal module synthesises a short sentence whose audio is passed to the audition module
- **THEN** Audition publishes an `audition.transcription` whose text contains the sentence's words, with `backend` `"sherpa_onnx"`

#### Scenario: A missing STT model disables transcription, not hearing
- **WHEN** Audition selects `"sherpa_onnx"` with transcription enabled and the package installed, but the Moonshine model directory is missing or incomplete
- **THEN** the audition module is registered with transcription disabled, so acoustic perception, vocal emotion and stimulus source audio continue; the failure is logged with the backend and the setup command; and the dashboard sherpa-onnx row reports DOWN with the reason

#### Scenario: Transcription off needs no STT backend
- **WHEN** Audition selects `"sherpa_onnx"` and `transcription_enabled` is false
- **THEN** no STT model is loaded, the extras check does not require `sherpa-onnx` for Audition, and Audition boots normally

#### Scenario: A missing TTS model disables Vocal
- **WHEN** the vocal module selects `"sherpa_onnx"` with the package installed but the Kokoro model directory missing or incomplete
- **THEN** the vocal module is not registered, the failure is logged with the backend and the setup command, the dashboard sherpa-onnx row reports DOWN with the reason, and the rest of the entity boots

#### Scenario: A missing package refuses the boot with an install hint
- **WHEN** a sherpa backend is selected for an enabled module and the `sherpa-onnx` package is not installed
- **THEN** the pre-boot extras check refuses to boot, naming the module and the `speech-edge` extra, as it does for every other missing optional dependency

### Requirement: Speech events disclose the backend and what reached the voice

`audition.transcription` and `vocal.synthesized` SHALL carry `"backend"` under every backend. `vocal.synthesized` SHALL carry `"prosody_applied"`, the list of prosody parameters that reached the voice. The field set SHALL be the same under every backend.

#### Scenario: Kokoro reports speed-only prosody
- **WHEN** the vocal module synthesises with `backend = "sherpa_onnx"`
- **THEN** `vocal.synthesized` carries `"backend": "sherpa_onnx"` and `"prosody_applied": ["speed_factor"]`

#### Scenario: Chatterbox reports the full parameter set
- **WHEN** the vocal module synthesises with the default backend
- **THEN** `vocal.synthesized` carries `"backend": "chatterbox"` and all four prosody parameters in `"prosody_applied"`

### Requirement: Speech models are fetched only with consent and verified

Speech model archives SHALL be pinned by URL and sha256 in code, and SHALL be downloaded only by an explicit setup command after the operator confirms each archive's name, size and licence. An archive SHALL be verified before extraction and extracted without escaping its target directory. Nothing SHALL be downloaded at runtime.

#### Scenario: Digest mismatch is refused
- **WHEN** a downloaded archive's sha256 differs from the pinned value
- **THEN** nothing is extracted and the command reports the mismatch

#### Scenario: Path traversal is refused
- **WHEN** an archive contains a member that would resolve outside its target directory, or a link
- **THEN** extraction is refused and nothing is written

#### Scenario: Declined consent downloads nothing
- **WHEN** the operator declines the confirmation
- **THEN** no network request is made and the command exits reporting that nothing was fetched

### Requirement: The health surface probes the selected speech backend

The dashboard health surface SHALL probe the Speaches or Chatterbox service only when its organ selects it. For `"sherpa_onnx"`, it SHALL report the organ healthy only after building the client and completing one real inference.

#### Scenario: Sherpa probe runs inference
- **WHEN** Audition selects `"sherpa_onnx"` and the health surface is read
- **THEN** the speech row reports UP only if the recogniser loaded and transcribed a short silent clip without error, and reports DOWN with the error otherwise

#### Scenario: A slow load never stacks
- **WHEN** a sherpa probe's model load takes longer than the prober's timeout and the health surface is read repeatedly
- **THEN** exactly one load runs for that model, the row reports DEGRADED "probe in progress" until it completes, and the completed result is reported afterwards
