# Audition paper revision note — 2026-11-16

Task 6.10 paper-revision pointer. Code references only; no paper code
changed by this note.

## Spectral / Dasheng / WavJEPPA encoders

- `kaine/modules/audition/acoustic.py`
  - `AcousticEncoder` (Protocol), `SpectralAcousticEncoder`
    (`spectral-logband-...-v2`), `build_acoustic_encoder`,
    `_dasheng_encoder_factory`, `_wavjepa_encoder_factory`.
- `kaine/modules/audition/ssl_encoders.py`
  - `_SelfSupervisedAcousticEncoder`, `DashengAcousticEncoder`,
    `WavJEPAAcousticEncoder`, `verify_weights`.
- Vendored sources:
  - `external/dasheng/` (config, feature extractor, model)
  - `external/wavjepa/` (config, model)
- Export/parity:
  - `scripts/export_audition_onnx.py`, `tests/test_audition_ssl_encoders.py`,
    `tests/test_audition_onnx_parity.py`, `tests/test_audition_encoder_selection.py`.

## Energy channel

- `kaine/modules/audition/acoustic.py` — `energy_dbfs(audio_bytes)`.
- `kaine/modules/audition/module.py` — `_estimate_energy`, perception payload
  key `energy_dbfs`; energy is a single scalar, never samples.

## Hearing stage

- `kaine/modules/audition/hearing_band.py` — `HearingBandParams`,
  `stage_edges`, `band_taps`, `band_frequency_response_db`.
- `kaine/modules/audition/hearing_stage_state.py` — `HearingStageState`.
- `kaine/cycle/hearing_stage_watch.py` — `HearingStageWatch`.
- `kaine/boot/perception_feed.py` — shared hearing-stage owner wiring
  (`_shared_hearing_stage_state`, stage file `hearing_stage.json`).

## Status

- 6.6/6.7/6.8/6.9 remain open; this note only collects code pointers for the
  eventual paper revision. No behaviour changed.
EOF