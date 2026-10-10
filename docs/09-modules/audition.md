# Audition

Audition is KAINE's raw hearing. It encodes each captured window of sound, predicts the next window's encoding from earlier ones and the broadcast context, and reports the prediction error to the workspace. On windows detected as speech it also classifies the tone of voice and predicts the tone with a second forward model. This page covers the microphone and feeds, the two forward models, the intensity and alert rule, the events, persistence, configuration, and the speech-to-text backends. Read it if you are enabling audio capture, choosing a speech-to-text backend, or interpreting `audition.*` events.

## Status

Implemented. The shipped `config/kaine.toml` sets `[modules].audition = false`, and the `thesis_test` profile (`config/profiles/thesis_test.toml`) enables it.

- The general acoustic path (`general_audition`) is off in the shipped `config/kaine.toml` and on in `thesis_test`. It makes Audition a sense for any sound, not only speech. Its default encoder, `SpectralAcousticEncoder`, needs only numpy and no download. The optional `dasheng` and `wavjepa` encoders need `torch`, `torchaudio`, and `einops` from the `[audio]` and `[internvideo]` extras; their weights load at the first `embed()` call, so a missing fetch fails at runtime, not at boot.
- Speech-to-text is off (`transcription_enabled = false`) in both the shipped `config/kaine.toml` and `thesis_test`. The client, model, and pipeline are built and bypassed unless an operator sets `transcription_enabled = true` in a local override. With it off, speech reaches the entity only as sound and tone of voice.
- The speech-to-text backend is `[audition].backend`: `"speaches"` (default; a Speaches faster-whisper service) or `"sherpa_onnx"` (Moonshine through sherpa-onnx, in-process, with no torch and no service). See [Backends](#backends).
- Vocal-emotion classification (`emotion2vec+`) and live microphone capture need the `[audio]` extras: `pip install -e .[audio]`. Without `funasr`, emotion degrades to neutral with a one-time warning. An empty `emotion_model_id` disables the classifier.
- Prosody extraction (`audition.prosody`) needs `librosa`, also in the `[audio]` extras.
- The tone forward model is always built once the module is enabled. It is a small CPU network that needs only `torch`.
- Audition is paired with [Vox](vox.md) for speech output.

## What Audition does

Audition is the architecture's analog of the auditory cortex, where sound is processed as prediction error against a learned model of the auditory environment. For each window that the microphone or a feed delivers (`process_audio()`):

1. Self-hearing suppression: while [Vox](vox.md) is playing the entity's own voice, a shared `SpeakingGate` drops the window.
2. General acoustic perception, when `general_audition` is on: Audition attends to the most recent part of the window (its length set by arousal), encodes it, steps the acoustic forward model, and publishes `audition.perception`. A voice-activity heuristic (`detect_speech()`) then decides whether the window is speech. Non-speech windows stop here. With `general_audition` off, every window is treated as speech.
3. Tone of voice: the emotion classifier labels the window, and speech-to-text runs alongside it only when `transcription_enabled = true` (both start together through `asyncio.gather()`).
4. The tone forward model steps on a 9-component vector built from the tone scores, the utterance's duration, and its energy, and its error grades the intensity of the speech-path events.
5. Prosody extraction, when `prosody_enabled = true`: a background task computes F0 statistics, RMS energy, and speaking rate from the in-memory audio and publishes `audition.prosody`.

Tone events carry how something was said, never what was said.

## Forward models

Both forward models are instances of `AuditoryForwardModel` (`kaine/modules/audition/forward.py`), a network with one hidden layer of tanh units run on the CPU:

```text
[input ‖ buffer mean ‖ broadcast context] → Linear(2·n + 24 → forward_model_units) → Tanh → Linear(forward_model_units → n)
```

The buffer mean is the mean of the last `auditory_buffer_size` inputs, the current one included. At each step the model scores the prediction made at the previous step against the current input (the error is the L2 distance, 0 on the first step), takes one stochastic-gradient step (learning rate 1e-3) on the mean squared error of that prediction from the same input it was made from, and then predicts the next input from the current input, the buffer mean, and the context Audition holds now. Every weight learns, the context weights included. The gradient step is skipped during sleep and whenever the loss or a gradient is not finite.

| Path | Input `n` | Input |
|---|---|---|
| Acoustic (general audition) | the encoder's `embedding_dim`: 64 for the spectral encoder, 768 for `dasheng` or `wavjepa` | The embedding of the attended part of the window |
| Tone (speech windows) | 9 | `[neutral, happy, sad, angry, surprised, fearful, disgusted, utterance_s / 30, mean_energy]`, where `utterance_s` is the window's duration in seconds (capped at 30) and `mean_energy` its RMS level in `[0, 1]` |

When the classifier fails, the tone model receives a fully neutral distribution.

### Broadcast context

Both models take the broadcast context as an extra input. Audition reads the workspace broadcast stream (`on_workspace`). When a broadcast arrives that is not inhibited, it keeps the coalition members whose scores reach the access threshold recorded in the broadcast's metadata (`access_threshold`); if at least one does, they become its new context. An inhibited broadcast, or one in which no member reaches the threshold, leaves the context unchanged, and before the first accessed broadcast the context slots are zeros. The context is the 24-component featurization of the accessed members weighted by their reported intensities, computed by `kaine/modules/context.py`; [Topos](topos.md#broadcast-context) lists its components. It records which modules' reports gained access and how strongly, and carries no payloads.

Audition holds no entity clock, so the age of its context (component 20 and `context_age_s`) is measured in wall-clock seconds since receipt. Wall-clock and entity seconds are equal at the default time scale.

### Cross-module information gain

The acoustic path also predicts from a null context, which keeps Audition's own share of the per-source and per-type components and replaces every other source's share, and the count and intensity statistics, with their means over the contexts Audition has adopted since boot. Each `audition.perception` event carries

```text
context_gain = (null-context error − error) / running mean error
```

over the last `prediction_error_window` acoustic errors. It is `null` when the scored prediction had no context or the running mean is zero. The null prediction never enters learning or the competition, and its running means restart with each boot. The tone path takes the context but computes no null prediction and reports no `context_gain`. The matched-selection and pooled arms of the planned test, and its positive control, are not built yet.

## Intensity and the alert flag

`audition.perception` (acoustic path). The error ratio is the acoustic error over the mean of the last `prediction_error_window` acoustic errors, the current one included. The window is an alert when the ratio is at least 2.0 (fixed in code) or when its cosine change from the previous embedding is at least `acoustic_change_alert_factor` times the mean of recent changes and at least `acoustic_change_alert_threshold`, an absolute floor. Typical alerts are a sudden sound, the onset of speech, an unexpected silence, or a shift in pitch or timbre. An alert is reported at `alert_salience`; any other window at

```text
baseline_salience + (alert_salience − baseline_salience) × min(1, ratio / 2)
```

`audition.emotion` (tone path). A non-neutral tone is an alert and is reported at `alert_salience`. A neutral tone is graded by the tone model's error ratio with the same formula. The payload's `alert` is true exactly when the tone is not neutral.

`audition.transcription` is graded by the tone model's error ratio. A failed classification or transcription is published at `alert_salience` with an `error` field and no `alert` flag. `audition.prosody` is always at `baseline_salience`.

The access rate's phasic input counts only events whose payload has `alert` set to true, so a failed classification does not raise the access rate. Thymos reads acoustic alerts directly from `audition.out` and raises arousal in proportion to how far `normalised_error` exceeds 1.

## Inputs

| Source | Mechanism | Purpose |
|---|---|---|
| `LiveMicrophone` task | `process_audio(bytes, sample_rate)` | Windows from the real microphone or an injected feed stream |
| Workspace broadcast | `on_workspace(snapshot)` | Adopts accessed broadcasts as the forward models' context |
| `kaine.perception_state` | `effective_audio_capture()`, polled every 250 ms | The real microphone runs only when the locus is `physical` and audio is desired |
| Vox `SpeakingGate` | `gate.is_speaking()` | Drops windows captured during the entity's own speech |
| External callers | `process_audio()` | Programmatic input, for example from a virtual-world body through Mundus |
| Thymos arousal | `set_arousal_provider()` (general audition only) | Sets the attended window |
| `hypnos.out` | `hypnos.sleep.started` / `hypnos.sleep.completed` | Suspends and resumes adaptation of both forward models |

## Outputs

All events are published to the `audition.out` stream.

| Event type | Payload fields | Intensity |
|---|---|---|
| `audition.perception` (general audition only) | `source_label`, `change_score`, `prediction_error`, `normalised_error`, `context_gain`, `context_age_s`, `alert`, `energy_dbfs`, `encoder_model_id`, `attended_window`, `attended_seconds`; `item` and `item_order` with a playlist feed | `alert_salience` on an alert, otherwise graded by the acoustic error ratio |
| `audition.emotion` | `category`, `alert`, `confidence`, `scores`, `model`, `source_label`, `latency_ms`, `prediction_error`; `degraded` when the classifier did not run | `alert_salience` for a non-neutral tone, otherwise graded by the tone error ratio |
| `audition.emotion` (failure) | `category` (`neutral`), `confidence`, `scores`, `model`, `source_label`, `latency_ms`, `error` | `alert_salience` |
| `audition.transcription` (only with `transcription_enabled = true`) | `text`, `backend`, `source_label`, `model`, `sample_rate`, `audio_bytes_length`, `latency_ms`, `prediction_error`; `error` on failure | Graded by the tone error ratio; `alert_salience` on failure |
| `audition.prosody` | `source_label`, `f0_mean_hz`, `f0_std_hz`, `f0_voiced_frac`, `rms_mean`, `rms_std`, `tempo_bpm` | `baseline_salience` |

`normalised_error` is the acoustic error ratio. `context_age_s` is the age of the held context in seconds, or `null` before the first accessed broadcast. `energy_dbfs` is the attended span's RMS level in dB full scale (floored at -120), computed independently of the encoder. `attended_window` is the fraction of the window that was encoded and `attended_seconds` the time it covered.

`source_label` is `"microphone"` for direct `process_audio()` calls and `"live_mic"` for utterances from the physical microphone; for a deterministic feed it is the feed mode's name. Emotion `category` is one of `neutral`, `happy`, `sad`, `angry`, `surprised`, `fearful`, `disgusted`, and `scores` carries the full seven-class distribution.

`audition.perception` is content-free: it carries numeric descriptors and the encoder's identity string, never audio or the embedding.

## Sleep

During sleep Hypnos switches the perception locus off and pauses a playlist feed's shared clock, so no windows reach Audition. Independently, both forward models are marked `suspended` from `hypnos.sleep.started` to `hypnos.sleep.completed`, and no gradient step is taken while the flag is set.

## Persistence

`serialize()` writes:

- `stt_model` and `emotion_model_id`, identity strings only;
- `forward_model`, the tone model's weight and bias tensors, with `forward_model_features = "utterance_duration_v2"`;
- `auditory_buffer_summary`, the tone model's buffer as a count and per-feature mean and variance;
- `acoustic_forward_models`, a map keyed by encoder `model_id`, each entry holding a `state_dict` and a `buffer_summary` for that encoder's acoustic forward model.

On restore:

- A tone checkpoint without the `utterance_duration_v2` tag, saved when that slot held a different feature, is discarded with a warning and the model learns again.
- A checkpoint of either model saved before the context input existed (first-layer input `2·n`) is accepted and loaded with zero weights for the 24 context inputs, so it predicts exactly as before until those weights learn. Any other shape mismatch is discarded with a warning.
- The acoustic checkpoint for the running encoder is loaded; checkpoints for other encoders are carried forward unchanged, so switching back to an encoder restores what it learned.
- The held context and the running statistics behind the null context are not persisted.

The serialized form contains no raw audio, no embeddings, and no buffers beyond the mean and variance summaries.

## Configuration

Section `[audition]` in `config/kaine.toml`. For the full reference see [Module configuration](../appendix-a-configuration/modules.md).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `backend` | string | `"speaches"` | Speech-to-text backend: `"speaches"` or `"sherpa_onnx"` |
| `sherpa_model_id` | string | `"moonshine-base-en"` | sherpa-onnx model: `"moonshine-base-en"` or `"moonshine-tiny-en"` |
| `sherpa_model_dir` | string | `<models dir>/sherpa-onnx/<id>` | Directory holding the downloaded sherpa-onnx model |
| `sherpa_num_threads` | integer | `2` | ONNX Runtime threads for sherpa-onnx |
| `speaches_url` | string | `"http://127.0.0.1:8000"` | Base URL of the Speaches server |
| `transcription_enabled` | boolean | `false` | Speech-to-text gate. When false the model is never invoked and no `audition.transcription` is published |
| `stt_model` | string | `"Systran/faster-distil-whisper-medium.en"` | Speaches model ID; it must be loaded on your Speaches instance or transcription returns 404 (list with `curl -s http://127.0.0.1:8000/v1/models`) |
| `emotion_model_id` | string | `"emotion2vec/emotion2vec_plus_base"` | funasr model for vocal emotion, resolved from HuggingFace; empty disables the classifier |
| `emotion_device` | string | `"cpu"` | Device for emotion2vec (about 90 M parameters; CPU recommended) |
| `request_timeout_s` | float | `60.0` | HTTP timeout for speech-to-text requests |
| `baseline_salience` | float | `0.4` | Baseline intensity of the graded range |
| `alert_salience` | float | `0.8` | Alert intensity, the top of the graded range |
| `capture_enabled` | boolean | `false` | Enable the live microphone; requires the `[audio]` extras |
| `capture_device` | string | `""` | Sound device name or index (empty for the OS default) |
| `capture_sample_rate` | integer | `16000` | Sample rate in Hz |
| `capture_channels` | integer | `1` | Channel count |
| `vad_backend` | string | `"webrtcvad"` | Voice-activity detector: `"webrtcvad"` or `"rms"` |
| `vad_aggressiveness` | integer | `2` | 0 to 3 for webrtcvad (higher is more aggressive) |
| `vad_frame_ms` | integer | `30` | Detector frame length (10, 20, or 30 ms) |
| `min_utterance_ms` | integer | `300` | Minimum utterance length passed on |
| `max_utterance_ms` | integer | `30000` | Maximum buffered utterance before a forced flush |
| `silence_hangover_ms` | integer | `600` | Silence after speech before a segment boundary |
| `desired_state_poll_ms` | integer | `250` | Poll interval of the locus gate |
| `forward_model_units` | integer | `32` | Hidden width of both forward models |
| `prediction_error_window` | integer | `32` | Steps in the running means of each path's error, and of the acoustic change score |
| `auditory_buffer_size` | integer | `16` | Inputs in each forward model's buffer |
| `prosody_enabled` | boolean | `false` | Publish `audition.prosody` through librosa |
| `general_audition` | boolean | `false` shipped; `true` in `thesis_test` | Encode every window and publish `audition.perception`; speech becomes a gated specialization. Boot also switches the live microphone to fixed-window continuous capture, so non-speech is heard (there is no separate `continuous_capture` key) |
| `arousal_window_min` | float | `0.15` | Attended fraction of the window at arousal 1.0 |
| `arousal_window_max` | float | `1.0` | Attended fraction of the window at arousal 0.0 (swap the two to widen under arousal) |
| `acoustic_change_alert_factor` | float | `2.0` | A change alert needs the change to be at least this multiple of its running mean |
| `acoustic_change_alert_threshold` | float | `0.35` | Absolute floor on the cosine change for a change alert |
| `acoustic_encoder` | string | `"spectral"` | `"spectral"` (numpy, no download), `"dasheng"` (Dasheng-base, Apache-2.0), or `"wavjepa"` (WavJEPA-base, MIT); see below |
| `acoustic_device` | string | `"cpu"` | Device for the self-supervised encoders, resolved like other module devices |

The `dasheng` and `wavjepa` encoders need their weights fetched once (`python -m kaine.setup.audio_ssl dasheng --yes`, or `wavjepa`). A plugin may also fill the `audition.acoustic_encoder` seam; setting `acoustic_encoder` to anything other than `spectral` while the seam is filled is a configuration error.

## General acoustic path

`_perceive_acoustic()` in `kaine/modules/audition/module.py`, backed by `kaine/modules/audition/acoustic.py`, runs these steps:

1. Attended window. `arousal_to_window()` maps the current Thymos arousal in `[0, 1]` linearly from `arousal_window_max` down to `arousal_window_min`, and `attend_recent()` keeps only that most recent fraction of the window (never less than one 25 ms frame). Higher arousal therefore means a shorter, more recent span, a temporal analogue of the narrowing of cue utilization under arousal (Easterbrook 1959). Arousal arrives through a provider wired at boot (`set_arousal_provider()`); with no provider the whole window is attended.
2. Encoding. `AcousticEncoder.embed(bytes, sample_rate)` turns the attended span into a fixed embedding. The default `SpectralAcousticEncoder` (encoder ID `spectral-logband-32-v2`) takes log energy in 32 log-spaced frequency bands, pools their mean and standard deviation over frames, and L2-normalizes the result into 64 dimensions; band edges are forced onto distinct FFT bins above DC, so all 32 bands carry information at 16 kHz. It represents speech, music, and environmental sound in one space. The frozen self-supervised encoders `dasheng` and `wavjepa` (student path only) are 768-dimensional at 16 kHz. They load offline from vendored code under `external/` and weights fetched at setup, and keep a RAM rolling window (2 s by default) of recent audio for context. Tests use `FakeAcousticEncoder`, a deterministic hash-based embedding.
3. Prediction and scoring. `cosine_change()` scores the change from the previous embedding, and the acoustic forward model steps as described above.
4. Publication of `audition.perception`.
5. Speech gate. `detect_speech()`, a cheap energy and spectral-centroid heuristic, sends speech windows on to the tone path.

A plugin can replace the encoder through the `audition.acoustic_encoder` seam, returning an object that satisfies the `AcousticEncoder` protocol (`embedding_dim`, `model_id`, and `embed(audio_bytes, sample_rate)`).

Stream separation, an attention schema for sound, and spatial localization are not built. They are tracked in [`openspec/changes/attention-driven-audition/tasks.md`](../../openspec/changes/attention-driven-audition/tasks.md).

## Backends

`[audition].backend` selects the speech-to-text recognizer, which runs only with `transcription_enabled = true`.

| Backend | Engine | Default | Notes |
|---|---|---|---|
| `speaches` | Speaches (faster-whisper) service | yes | OpenAI-compatible local server; it must have `stt_model` loaded |
| `sherpa_onnx` | sherpa-onnx Moonshine | no | In-process, no torch. Moonshine base English, 111 MB (MIT), or tiny English, 30 MB (MIT) |

With `backend = "speaches"`, `SpeachesClient.transcribe()` POSTs multipart form data (`model`, `file=audio.wav`) to `/v1/audio/transcriptions` through `httpx`. With `backend = "sherpa_onnx"`, `SherpaSTT` (`kaine/modules/audition/sherpa_stt.py`) runs Moonshine in-process on the same in-memory WAV bytes. Download its models ahead of time:

```bash
python -m kaine.setup.speech_models --stt moonshine-base-en
```

The command shows name, size, and licence and asks for consent. Archives are pinned by URL and sha256, verified, and extracted into `state/models/sherpa-onnx/`; running it twice is harmless, and nothing downloads at runtime. On a desktop CPU, Moonshine base transcribes a 3 s sentence in about 40 ms.

Limits:

- sherpa-onnx publishes `audition.transcription` with `"backend": "sherpa_onnx"`.
- The Nexus health surface probes Speaches only when `backend = "speaches"`. For sherpa-onnx it loads the model and runs one real inference once per process, then reports the remembered result with its age; a failure is retried after 60 s.
- A missing `sherpa-onnx` package refuses boot through the extras check (`pip install "kaine[speech-edge]"`) only when transcription is enabled.
- A missing or corrupt model, with either backend, disables transcription only. Audition keeps hearing and reporting tone, the reason is logged, and the Nexus row shows DOWN.

## Emotion classification

`Emotion2vecClassifier` wraps `funasr.AutoModel` for `emotion2vec/emotion2vec_plus_base` (about 90 M parameters). It loads lazily on the first classification and degrades to a neutral stub if `funasr` is missing. Audio is passed as `io.BytesIO`, with an in-memory float32 array as a fallback, so nothing is written to disk. Labels are normalized to the seven-class set.

## Prosody extraction

`extract_prosody()` works on a one-dimensional float32 array decoded from the in-memory audio. It uses `librosa.pyin` for F0 with a voiced flag, `librosa.feature.rms` for energy statistics, and `librosa.feature.tempo` for speaking rate. Non-finite values become 0.0, and the array is released when the function returns.

## Deterministic auditory feed

For reproducible research runs, the shared top-level `[perception_feed]` section (documented under [Topos](topos.md#reproducible-perception-feed)) drives Audition alongside Topos from one source. When `[perception_feed].mode` is `seeded`, `playlist`, `screen`, or `womb`, boot injects an audio stream factory through Audition's `stream_factory` seam and forces capture on, so `LiveMicrophone` reads from the feed instead of the real microphone:

- `seeded`: `SeededProceduralAudioStream` synthesizes int16 PCM as a pure function of `(seed, block_index)`, a learnable base soundscape of low-frequency sinusoids plus surprise bursts on the shared cross-modal cadence (`[perception_feed.video].surprise_interval`). It is sound, not speech.
- `playlist`: `PlaylistAudioStream` decodes the audio track of the same checksummed manifest media through PyAV (`av`, in the `[audio]` extra), resamples it, and emits PCM. A digest mismatch fails closed; without PyAV it raises `PerceptionUnavailableError` with an install hint and never substitutes silence. To install both playlist surfaces in one step, use `bash scripts/install.sh --research` or `pip install -e .[perception]`.
- `screen`: `MonitorAudioStream` (`kaine/modules/audition/monitor.py`) captures the desktop audio monitor through the system ffmpeg binary (`pulse` on Linux, `dshow` on Windows, `avfoundation` on macOS), so the entity hears whatever plays on the shared screen. The device comes from `[perception_feed.screen].monitor_device` (on Linux the current sink's `.monitor` when unset). It is not reproducible and is for demos with an operator present.
- `womb`: the gestation audio source; see [Gestation](../06-operation/gestation.md).

Raw PCM lives only in memory, never on disk.

## Live microphone logging

Each flushed chunk logs at DEBUG. An INFO summary is logged every `LiveMicConfig.summary_interval_s` (300 s by default, with no TOML key):

```
live mic: N chunks (B pcm bytes) flushed, K below minimum…
```

## Nexus live-preview tap

`_tap_audio_level()` in `kaine/modules/audition/live.py` computes the normalized RMS (0 to 1) of each captured PCM frame and hands it to the in-memory preview holder through `perception_preview.set_audio_level()`, which feeds the Nexus audio-level meter. Unless the operator sets `KAINE_PERCEPTION_PREVIEW=1` it does nothing, and it keeps only the current value.

## Key files

| File | Role |
|---|---|
| `kaine/modules/audition/module.py` | `Audition` class: `process_audio()`, `_perceive_acoustic()`, intensity and alert rules, context adoption, publish helpers, serialization |
| `kaine/modules/audition/forward.py` | `AuditoryForwardModel` with its context input, `build_feature_vector()` |
| `kaine/modules/context.py` | `BroadcastContext`: context featurization, adoption, null context |
| `kaine/modules/intensity.py` | `graded_intensity()`, shared by the four predictive processors |
| `kaine/modules/audition/acoustic.py` | `AcousticEncoder` protocol, `SpectralAcousticEncoder`, `FakeAcousticEncoder`, `cosine_change()`, `arousal_to_window()`, `detect_speech()` |
| `kaine/modules/audition/ssl_encoders.py` | Frozen self-supervised acoustic encoders (`dasheng`, `wavjepa`) |
| `kaine/setup/audio_ssl.py` | Weight setup for the self-supervised encoders |
| `kaine/modules/audition/emotion.py` | `Emotion2vecClassifier`, `EmotionResult`, `CATEGORIES` |
| `kaine/modules/audition/stt_client.py` | `SpeachesClient`, the `STTClient` protocol, `TranscriptionResult` |
| `kaine/modules/audition/sherpa_stt.py` | sherpa-onnx Moonshine backend |
| `kaine/modules/audition/prosody.py` | `extract_prosody()`, `audio_bytes_to_float32()` |
| `kaine/modules/audition/live.py` | `LiveMicrophone`: voice-activity supervisor, locus gate |
| `kaine/modules/audition/feed.py` | Deterministic audio sources and the stream factory wiring |
| `kaine/modules/audition/monitor.py` | `MonitorAudioStream` for screen audio |

## Enabling and use

```toml
# local config/kaine.toml (do not commit)
[modules]
audition = true

[audition]
capture_enabled = true    # requires pip install -e .[audio]
```

To hear any sound, not only speech:

```toml
[audition]
general_audition = true                  # spectral encoder: numpy only, no download
# arousal_window_min = 0.15              # attended fraction at full arousal
# arousal_window_max = 1.0               # attended fraction at zero arousal
# acoustic_change_alert_factor = 2.0
# acoustic_change_alert_threshold = 0.35
```

To enable prosody extraction:

```toml
[audition]
prosody_enabled = true    # requires librosa (in the [audio] extras)
```

The `thesis_test` profile turns `general_audition` on and leaves `transcription_enabled` off, so audio enters only as prediction error and tone, and no text reaches Lingua. To re-enable speech-to-text, which takes the configuration beyond the base-thesis form:

```toml
[audition]
transcription_enabled = true
```

For `backend = "speaches"`, start Speaches first. Run Whisper on the CPU with model `medium.en` to avoid 404 and cuDNN crashes (see [Troubleshooting](../06-operation/troubleshooting.md)):

```bash
speaches --model medium.en --device cpu
```

For `backend = "sherpa_onnx"`, fetch the model before enabling transcription (see [Backends](#backends)).

## Zero-persistence note

Audition holds no raw audio beyond a single `process_audio()` call, except that the `dasheng` and `wavjepa` encoders keep up to `context_s` (2.0 s) of decoded PCM in RAM across calls. That buffer is never written to disk. In `live.py`, PCM lives in a bounded `asyncio.Queue` and the WAV blob in a `BytesIO`, and all references are released when `process_audio()` returns. No temporary file, no `.wav` file, and no raw audio bytes reach disk or the bus; `audition.prosody` and `audition.perception` carry only numbers and identity strings.

## Tests

| File | What it verifies |
|---|---|
| `tests/test_audition_module.py` | `process_audio()` orchestration, error paths, serialization; general-audition wiring, `audition.perception` publication, non-speech gating, speech specialization, arousal seam |
| `tests/test_audition_forward.py` | `AuditoryForwardModel` step, non-finite guard, error-graded intensity |
| `tests/test_forward_model_context.py` | Context input of the forward models, null-context error, restore of checkpoints saved before the context input |
| `tests/test_broadcast_context.py` | Context featurization, adoption of accessed members, inhibited broadcasts, null context |
| `tests/test_graded_intensity.py` | The shared graded-intensity rule |
| `tests/test_audition_acoustic.py` | Encoder shape and unit norm, distinct embeddings, `cosine_change`, `arousal_to_window` narrowing, `detect_speech` routing |
| `tests/test_audition_persistence.py` | Acoustic forward-model persistence round trip, shape-mismatch discard, encoder switch and back, sleep suspension, zero persistence of the new key |
| `tests/test_audition_encoder_selection.py` | Encoder registry, factory config, plugin seam, `construct_module` injection |
| `tests/test_audition_emotion.py` | `Emotion2vecClassifier` wrapping, label normalization, degradation |
| `tests/test_audition_stt_client.py` | `SpeachesClient` HTTP logic |
| `tests/test_sherpa_speech_engines.py` | sherpa-onnx engine setup and model loading |
| `tests/test_sherpa_speech_live.py` | sherpa-onnx live transcription path |
| `tests/test_audition_prosody.py` | `extract_prosody()` features, zero persistence |
| `tests/test_audition_live.py` | `LiveMicrophone` voice-activity loop, locus gate |
| `tests/test_audition_live_logging.py` | Live-microphone summary interval and message format |
| `tests/test_audio_self_hearing.py` | `SpeakingGate` self-hearing suppression |
| `tests/test_audition_feed.py` | Seeded audio (determinism, seek safety, seed decorrelation), playlist audio (manifest verification failing closed, PyAV absent), and `womb` |
| `tests/systems/test_audition_subsystem.py` | Redis-backed subsystem integration |

## Spec and related

- OpenSpec (base): [`openspec/specs/audition/spec.md`](../../openspec/specs/audition/spec.md)
- OpenSpec (predictive): [`openspec/specs/audition-predictive/spec.md`](../../openspec/specs/audition-predictive/spec.md)
- OpenSpec (prosody): [`openspec/specs/audition-prosody/spec.md`](../../openspec/specs/audition-prosody/spec.md)
- OpenSpec (change): [`openspec/changes/attention-driven-audition/proposal.md`](../../openspec/changes/attention-driven-audition/proposal.md), general auditory perception
- Related modules: [Perception](perception.md) (locus arbiter), [Vox](vox.md) (speech output, self-hearing gate), [Topos](topos.md) (vision), [Thymos](thymos.md) (arousal and tone appraisal)
- Cognitive cycle: [The cognitive cycle](../08-cognitive-cycle/README.md) and [The global workspace](../08-cognitive-cycle/global-workspace.md)
