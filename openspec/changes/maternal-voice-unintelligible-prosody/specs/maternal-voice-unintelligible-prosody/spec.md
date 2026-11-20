## Purpose

Sam renderer as contract-honest alternate backend for unintelligible (prosody-only) maternal voice, with validated checkpoint boundary and manifest provenance.

## Requirements

### Requirement: Sam backend resampling determinism
The system SHALL resample the Sam path with `res_type="soxr_hq"` in `librosa.resample`.

### Requirement: Chatterbox-only reference directory
The system SHALL gate `--reference-dir` as Chatterbox-only (help text and code paths).

### Requirement: Checkpoint boundary validation
The system SHALL assert checkpoint `config.json`: `spk_id["sam"]==3000`, `tts_model_type=="custom_voice"` for local-path source, raising (no silent fallthrough) otherwise.

### Requirement: Sam generation provenance
The system SHALL record Sam generation provenance (`generation_params`: `"model defaults (not exposed)"` or named constants).

### Requirement: Exposed helpers for test import
The system SHALL expose/alias `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ` for test import so plan and generator cannot drift.

### Requirement: Adapter-boundary validation
The system SHALL add adapter-boundary validation in `render_maternal_voice_sam.build_render_plan()` (rate 8000, FLAC, PCM_16, ceiling 300).

### Requirement: Unintelligible prosody content
The system SHALL use syllable/nonlexical prosody content (no intelligible words) for the unintelligible stimulus.

### Requirement: 300 Hz low-pass agreement
The system SHALL ensure `SPECTRAL_CEILING_HZ`/`lowpass_hz`/`lowpass_cutoff_hz` all agree at 300.

### Requirement: Sam manifest provenance
The system SHALL emit `generation_params` and `resampler="soxr_hq"` in Sam `generator` block.

### Requirement: Reference voice correctness for Sam
The system SHALL keep `reference_voice.attribution` and empty `files` correct for Sam; no reference WAV produced/consumed.

## Scenarios

### Scenario: Sam resampling uses soxr_hq
- **WHEN** the Sam path resamples audio
- **THEN** it uses `res_type="soxr_hq"`.

### Scenario: Reference dir gated to Chatterbox
- **WHEN** `--reference-dir` is passed with `--renderer sam`
- **THEN** it is rejected as Chatterbox-only.

### Scenario: Checkpoint boundary enforced
- **WHEN** a local Sam checkpoint lacks `spk_id["sam"]==3000` or `tts_model_type=="custom_voice"`
- **THEN** an error is raised with no silent fallthrough.

### Scenario: Generation params recorded honestly
- **WHEN** Sam renders
- **THEN** `generation_params` is `"model defaults (not exposed)"` or named constants; nothing implied.

### Scenario: Helpers importable for tests
- **WHEN** tests import `apply_prosody_muffling` and `SPECTRAL_CEILING_HZ`
- **THEN** they resolve to the same objects used by plan and generator.

### Scenario: Adapter boundary validated
- **WHEN** `build_render_plan()` runs
- **THEN** it asserts `output_sample_rate==8000`, `output_format=="FLAC"`, `subtype=="PCM_16"`, `spectral_ceiling_hz==300`.

### Scenario: Syllable content used
- **WHEN** the Sam stimulus is rendered
- **THEN** content is syllable/nonlexical with no intelligible words.

### Scenario: Ceiling spellings agree at 300
- **WHEN** manifest is emitted
- **THEN** `SPECTRAL_CEILING_HZ`/`lowpass_hz`/`lowpass_cutoff_hz` are all 300.

### Scenario: Sam never downloads CMU-ARCTIC
- **WHEN** Sam runs
- **THEN** it never attempts CMU-ARCTIC download.

### Scenario: Sam manifest keeps attribution/files
- **WHEN** Sam manifest is emitted
- **THEN** `reference_voice.attribution` remains correct and `files` is empty.