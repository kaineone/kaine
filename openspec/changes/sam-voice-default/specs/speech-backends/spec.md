# Spec Delta

## MODIFIED Requirements

### Requirement: Speech models are fetched only with consent and verified

Speech model archives SHALL be pinned by URL and sha256 in code, and SHALL be downloaded only by an explicit setup command after the operator confirms each archive's name, size and licence. An archive SHALL be verified before extraction and extracted without escaping its target directory. Nothing SHALL be downloaded at runtime. When the vocal backend is `"qwen3_tts"`, the provisioning plan SHALL include the configured Qwen3-TTS HuggingFace model as an aux model entry, so the setup wizard downloads it alongside the other HuggingFace models. The download SHALL use the same `huggingface_hub` path as other aux models and SHALL require the same operator consent.

#### Scenario: Digest mismatch is refused
- **WHEN** a downloaded archive's sha256 differs from the pinned value
- **THEN** nothing is extracted and the command reports the mismatch

#### Scenario: Path traversal is refused
- **WHEN** an archive contains a member that would resolve outside its target directory, or a link
- **THEN** extraction is refused and nothing is written

#### Scenario: Declined consent downloads nothing
- **WHEN** the operator declines the confirmation
- **THEN** no network request is made and the command exits reporting that nothing was fetched

#### Scenario: Qwen3-TTS model appears in the provision plan
- **WHEN** the vocal backend is `"qwen3_tts"` and `aux_models()` is called with that config
- **THEN** the returned list includes an `AuxModel` whose repo matches the configured (or default) `qwen3_model_id`

#### Scenario: Qwen3-TTS model is not provisioned for other backends
- **WHEN** the vocal backend is `"chatterbox"` or `"sherpa_onnx"`
- **THEN** no Qwen3-TTS model appears in the aux model list

## ADDED Requirements

### Requirement: Qwen3-TTS backend reports its speaker in prosody metadata

When the vocal backend is `"qwen3_tts"`, `vocal.synthesized` SHALL carry `"backend": "qwen3_tts"` and SHALL carry the resolved speaker name in `"prosody_applied"` metadata, consistent with the other backends' disclosure.

#### Scenario: Qwen3-TTS prosody disclosure
- **WHEN** the vocal module synthesises with `backend = "qwen3_tts"`
- **THEN** `vocal.synthesized` carries `"backend": "qwen3_tts"` and `"prosody_applied"` includes `"instruct"` and `"language"`
