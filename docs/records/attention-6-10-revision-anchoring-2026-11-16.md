# Attention 6.10 revision anchoring — 2026-11-16

Task docs only. Anchors code references for the attention-driven-audition
task 6.10 paper revision note ("the encoder class, and 'over raw waveform'
refined if the winner computes a mel spectrogram inside the model"). No paper
source is present in this repository; no paper files are modified by this note.
No task checkboxes are changed.

## Current audition types (encoders / schedules / payloads)

- `kaine/modules/audition/acoustic.py`
  - `AcousticEncoder` (Protocol), `SpectralAcousticEncoder`
    (`spectral-logband-...-v2`), `build_acoustic_encoder`,
    `_dasheng_encoder_factory`, `_wavjepa_encoder_factory`,
    `energy_dbfs(audio_bytes)`, `arousal_to_window`, `detect_speech`.
- `kaine/modules/audition/ssl_encoders.py`
  - `_SelfSupervisedAcousticEncoder`, `DashengAcousticEncoder`,
    `WavJEPAAcousticEncoder`, `verify_weights`.
- `kaine/modules/audition/feed.py`
  - `SeededAudioSchedule`, `StimulusSourceAudioSchedule`,
    `SeededProceduralAudioStream`, `StimulusSourceProceduralAudioStream`,
    `PlaylistAudioStream`, `_ItemTimeline`.
- `kaine/modules/audition/module.py`
  - `Audition` (`BaseModule`), `_estimate_energy`, perception payload key
    `energy_dbfs`; acoustic perception payload remains content-free.
- Vendored sources: `external/dasheng/`, `external/wavjepa/`.
- Export/parity: `scripts/export_audition_onnx.py`,
  `tests/test_audition_ssl_encoders.py`, `tests/test_audition_onnx_parity.py`,
  `tests/test_audition_encoder_selection.py`,
  `tests/test_audition_feed_replay.py`.

## Hearing stage

- `kaine/modules/audition/hearing_band.py` — `HearingBandParams`,
  `stage_edges`, `band_taps`, `band_frequency_response_db`.
- `kaine/modules/audition/hearing_stage_state.py` — `HearingStageState`.
- `kaine/cycle/hearing_stage_watch.py` — `HearingStageWatch`.
- `kaine/boot/perception_feed.py` — shared hearing-stage owner wiring
  (`_shared_hearing_stage_state`, stage file `hearing_stage.json`).

## Energy channel

- `kaine/modules/audition/acoustic.py` — `energy_dbfs(audio_bytes)`.
- `kaine/modules/audition/module.py` — `_estimate_energy`, perception payload
  key `energy_dbfs`; energy is a single scalar (dBFS), never samples/PCM.

## Bench report

- Primary bake-off: `docs/records/audition-encoder-bakeoff.json`.
- 1200-block snapshot: `docs/records/audition-encoder-bakeoff-1200blocks.json`.
- Decision summary: `docs/records/audition-encoder-decision-note-2026-11-16.md`.
- Synthetic feed record: `docs/records/audition-feed-bench-synthetic.json`.
- Harness: `scripts/bench_audition_encoders.py`.
- Prior encoders-only paper pointer: `docs/records/audition-paper-revision-note-2026-11-16.md`.

## Status

- 6.6/6.7/6.8/6.9 remain open per the decision note; this anchoring note
  only collects code pointers and file references. No behaviour changed.
- Winner is not yet promoteable; Tier 0 remains `spectral`. Paper-side
  "over raw waveform" wording stays as in the already-updated paper.