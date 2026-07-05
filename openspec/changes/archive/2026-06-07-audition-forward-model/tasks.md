## 1. Auditory forward model

- [x] 1.1 `kaine/modules/audition/forward.py` — forward model over compact auditory feature vector (emotion distribution + timing/energy); online step; non-finite guard
- [x] 1.2 Bounded recurrent auditory buffer; salience driven by prediction error

## 2. Prosody extraction

- [x] 2.1 `kaine/modules/audition/prosody.py` — in-memory prosody extraction using **librosa** (ISC): F0 via `librosa.pyin`, energy via RMS, tempo via `librosa.beat.tempo`; all computed on a NumPy array held in memory — no `NamedTemporaryFile`, no disk I/O; numeric features only
- [x] 2.2 Publish `audition.prosody` (no raw audio); gated by `prosody_enabled`

## 3. Module + config

- [x] 3.1 Wire forward model + prosody into `Audition`; weight prediction error into transcription/emotion salience
- [x] 3.2 `[audition]` config: `forward_model_units`, `prediction_error_window`, `auditory_buffer_size`, `prosody_enabled`; update `make_audition` allowed keys (remove `prosody_backend`)
- [x] 3.3 Add `librosa` to the optional `[audio]` extra in `pyproject.toml`; remove any `parselmouth` dependency

## 3a. Zero-persistence audit

- [x] 3a.1 Audit the FunASR STT path for any `NamedTemporaryFile` or `.wav` file writes; replace with `BytesIO` or an in-memory FIFO so that no raw audio bytes are written to disk at any point

## 4. Tests

- [x] 4.1 `tests/test_audition_forward.py` — predictor shape; error drops on a repeating pattern; unexpected tone raises salience
- [x] 4.2 `tests/test_audition_prosody.py` — feature extraction on a synthetic waveform; payload carries numeric features only (no bytes)
- [x] 4.3 `tests/test_audition_module.py` — `audition.prosody` published when enabled; zero-persistence preserved

## 5. Verification

- [x] 5.1 Full unit suite green
- [x] 5.2 `openspec validate audition-forward-model --strict` clean
- [x] 5.3 Commit (Kaine.One), branch-per-change, merge, archive
