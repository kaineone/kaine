# Reconcile the audio-input and audio-output specs with the code

## Why

The `audio-input` and `audio-output` specs hold the behavioural requirements for hearing and speech, but they describe modules that no longer exist under those names. They name `AudioInput` and `AudioOutput`, the `[audio_in]` and `[audio_out]` tables, and the `audio.in.out` stream. The modules are Audition and Vox, configured under `[audition]` and `[vox]`.

A requirement-by-requirement check against the code found three behaviours that have changed:
- **Transcription is off by default.** With `[audition].transcription_enabled = false`, a capture publishes only an emotion event.
- **Self-hearing suppression drops the whole capture.** A capture caught by the speaking gate publishes no transcription, emotion or perception event. The spec said only the transcription was dropped.
- **The gate is checked on delivery.** Audition checks it when a finished capture arrives, not when the utterance began.

The specs also left out the opt-in sherpa-onnx backends (Moonshine for STT, Kokoro for TTS), the null emotion classifier, Vox's dormant and muted states, and the default `retain_count` of 0.

## What changes

- Every stale requirement in both specs is restated to match the code, with its names, defaults, events and payloads.
- Three requirements are renamed:
  - Default AudioInput config → Default Audition config;
  - AudioOutput subscribes to lingua.external → Vox subscribes to lingua.external;
  - Default AudioOutput config → Default Vox config.
- New scenarios cover transcription being off by default, the null emotion classifier, the opt-in backends, dormant and muted Vox, and the speaking-gate drop.
- Audition docstrings that still said "AudioInput" now say Audition.

## Found, not changed here

`make_vox` builds its backend registry with `default="sherpa_onnx"` while the shipped and factory default is `"chatterbox"`. The registry default is never reached, because the factory resolves the backend first, but it contradicts the real default. It lives in the boot code, which is being split into a package, so it is fixed after that lands.

## Impact

- **Behaviour:** none. The specs and three docstrings change to describe the code.
- **Research:** none.
