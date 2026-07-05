## Why

`KAINE_Paper_v4.md` §3.3.1 specifies Audition with **a small forward model that
predicts expected auditory patterns**, where prediction errors (unexpected
sounds, unexpected silence, unexpected emotional tone) drive auditory salience,
over a recurrent auditory buffer. Today Audition transcribes (Speaches/
distil-Whisper) and classifies emotion (emotion2vec+) but only *reports* what
arrives — it does not predict, so an expected reply and a jarring interruption
are equally salient.

This change also adds **speaker prosody extraction**, which Audition is the
natural owner of and which `vox-prosodic-mirroring` (§3.3.4) consumes to produce
vocal accommodation. Extracting it here keeps the perception/expression
dependency one-directional (Audition → bus → Vox).

## What Changes

- Add `kaine/modules/audition/forward.py`: a forward model over a compact
  auditory feature vector (emotion-class distribution + utterance timing/energy
  features) predicting the next expected pattern; salience driven by prediction
  error. Recurrent auditory buffer for temporal context.
- Add `kaine/modules/audition/prosody.py`: extract per-utterance prosodic
  features (pitch/F0 contour summary via `librosa.pyin`, energy via RMS, speaking
  rate via `librosa.beat.tempo`) from the captured audio as a NumPy array held
  in memory — no disk I/O, no NamedTemporaryFile. Published as `audition.prosody`
  (numeric features only — no raw audio, preserving zero-persistence). The STT
  path (FunASR) is also audited to eliminate any `.wav` file writes in favour of
  in-memory (`BytesIO`) transport.
- Salience for `audition.transcription`/`audition.emotion` becomes prediction-
  error-weighted; unexpected emotional tone raises salience.
- `[audition]` config gains: `forward_model_units`, `prediction_error_window`,
  `auditory_buffer_size`, `prosody_enabled`.

## Capabilities

### New Capabilities

- `audition-predictive`: auditory forward model + prediction-error salience +
  recurrent auditory buffer.
- `audition-prosody`: in-memory speaker-prosody feature extraction published as
  numeric features for downstream vocal accommodation.

### Modified Capabilities

None.

## Impact

- **Depends on:** `audition` (the renamed `audio-input`; see
  `rename-audition-vox`). **New dep:** `librosa` (ISC licence) as an optional
  `[audio]` extra; no parselmouth dependency.
- **Privacy:** prosody features are numeric summaries computed in memory from a
  transient NumPy array; raw audio is released immediately after feature
  extraction and never written to disk or placed on the bus.
- **Consumed by:** `thymos-affect-coupling` (emotion + prediction error),
  `vox-prosodic-mirroring` (`audition.prosody`).
