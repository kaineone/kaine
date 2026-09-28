## Context

**Audition** (`kaine/modules/audition/`):
- Capture and VAD (`live.py`) produce an in-memory 16-bit WAV per utterance and await `Audition.process_audio`.
- It runs transcription through an `STTClient` (`stt_client.py`: async `transcribe(audio_bytes, *, sample_rate, model, filename) -> TranscriptionResult(text, model, latency_ms, raw)`, and `aclose()`).
- The default `SpeachesClient` POSTs to a Speaches service.
- A failed transcription publishes `audition.transcription` with empty text and `error`.

**Vox** (`kaine/modules/vox/`):
- It maps affect (plus prosodic mirroring) to `ChatterboxParams(temperature, exaggeration, cfg_weight, speed_factor)`.
- It builds a `TTSRequest` and calls a `TTSClient` (`client.py`: async `synthesize(req) -> SynthesisResult(audio, content_type, latency_ms, output_format, bytes_produced)`).
- The default `ChatterboxClient` POSTs to a Chatterbox service.
- Playback reads the sample rate from the WAV header and requires 16-bit.
- A failure publishes `vox.synthesized` with `success=False`.

`runtime-backends` requires the following:
- `[<module>].backend` keys;
- defaults that reproduce Tier 2;
- lazy imports;
- a failed backend that falls back or disables with a surfaced reason, and never crashes the boot.

`kaine/modules/backends.py` (`BackendRegistry`, `resolve_backend`, `record_backend_failure`) implements this. Lingua is its only user today.

## Decisions

### Backends and wiring
- **Keys.**
  - `[audition].backend`: `"speaches"` (default) | `"sherpa_onnx"`.
  - `[vox].backend`: `"chatterbox"` (default) | `"sherpa_onnx"`.
  - Each is resolved in `make_audition`/`make_vox` through a `BackendRegistry` per module, with no fallback declared for `sherpa_onnx`.
  - An unknown name is a `ConfigurationError`.
  - A missing `sherpa-onnx` package is caught first by the existing extras pre-flight, which refuses the boot and names the `speech-edge` extra, as for every missing optional dependency.
  - A factory failure at construction (missing or corrupt model files, an invalid speaker) is recorded with `record_backend_failure`, and the module is not registered. The boot continues, and the health surface shows the reason.
- **New keys**, added to the boot allow-lists and `config/kaine.toml` with comments:
  - `[audition].sherpa_model_dir` (default empty, meaning `models_dir() / "sherpa-onnx" / "moonshine-base-en"`);
  - `[audition].sherpa_num_threads` (default 2);
  - `[vox].sherpa_model_dir` (default empty, meaning `models_dir() / "sherpa-onnx" / "kokoro-en"`);
  - `[vox].sherpa_speaker_id` (default 0, a public preset);
  - `[vox].sherpa_num_threads` (default 2).
- **`SherpaMoonshineSTT`** (`kaine/modules/audition/sherpa_stt.py`) implements `STTClient`.
  - Construction imports `sherpa_onnx`, validates the model directory (`encoder_model.ort`, `decoder_model_merged.ort`, `tokens.txt`), and builds `OfflineRecognizer.from_moonshine_v2(encoder=, decoder=, tokens=, num_threads=)`. It raises a clear error if anything is missing.
  - `transcribe`:
    - decodes the WAV (16-bit PCM, mono or first channel) to float32 in [−1, 1];
    - creates a stream and calls `accept_waveform(sample_rate, samples)` (sherpa-onnx resamples);
    - decodes and returns `TranscriptionResult(text=result.text.strip(), model=<model id>, latency_ms, raw={})`.
  - Inference runs in a dedicated `ThreadPoolExecutor(max_workers=1)`, so the event loop never blocks and the recogniser is never used concurrently.
  - `aclose` shuts the executor down.
- **`SherpaKokoroTTS`** (`kaine/modules/vox/sherpa_tts.py`) implements `TTSClient`.
  - Construction builds `OfflineTts(OfflineTtsConfig(model=OfflineTtsModelConfig(kokoro=OfflineTtsKokoroModelConfig(model=model.int8.onnx, voices=voices.bin, tokens=tokens.txt, data_dir=espeak-ng-data), num_threads=)))`, and validates `speaker_id` against `num_speakers`.
  - `synthesize(req)` calls `generate(req.text, sid=speaker_id, speed=req.speed_factor)` in the worker thread. It clamps the speed to the range sherpa-onnx accepts, converts the float samples to 16-bit PCM, and returns WAV bytes at `audio.sample_rate`.
  - Other request fields are ignored, and that is disclosed (below).
  - An empty or whitespace text returns an error, as Chatterbox would reject it.

### Disclosure
- `audition.transcription` gains `"backend"` (`"speaches"` or `"sherpa_onnx"`) on success and on error.
- `vox.synthesized` gains `"backend"`, plus `"prosody_applied"`: the list of prosody parameters that reached the voice (`["temperature", "exaggeration", "cfg_weight", "speed_factor"]` for Chatterbox, `["speed_factor"]` for Kokoro).
- The field set is the same under every backend, so selecting a backend does not change the event shape. The existing exact-key-set tests are updated once.

### Models and consent
- `kaine/setup/speech_models.py` holds a manifest of the sherpa-onnx model archives. Each entry has an id, URL, sha256, size, licence and target directory.
  - The archives are sherpa-onnx release assets (`https://github.com/k2-fsa/sherpa-onnx/releases/download/<tag>/<name>`), fetched and hashed on 2026-09-27:

| id | archive | size | sha256 | licence |
|---|---|---|---|---|
| `moonshine-base-en` (STT default) | `asr-models/sherpa-onnx-moonshine-base-en-quantized-2026-02-27.tar.bz2` | 111,266,225 B | `43232c1d13013d37317163baec3135bd771a186a4356f28c889bab453bb0e891` | MIT |
| `moonshine-tiny-en` | `asr-models/sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27.tar.bz2` | 29,858,559 B | `9ec31b342d8fa3240c3b81b8f82e1cf7e3ac467c93ca5a999b741d5887164f8d` | MIT |
| `kokoro-en` (TTS default) | `tts-models/kokoro-int8-en-v0_19.tar.bz2` | 103,248,205 B | `c9f0dd393615805b0bab050c340834d5e684e732aec91c0e860cd30e982c08bd` | Apache-2.0 |

  - An archive whose digest differs is rejected. The archives contain only regular files and directories.
  - Verified on the development host with sherpa-onnx 1.13.8 imported from a scratch directory (not installed): Kokoro speaker 0 synthesised "The quick brown fox jumps over the lazy dog." (24 kHz, 11 speakers, 1.3 s cold), and Moonshine base transcribed it back exactly in 40 ms. Half a second of silence transcribes to an empty string.
- `python -m kaine.setup.speech_models [--stt ID] [--tts ID] [--yes]`:
  - prints each archive's name, size and licence;
  - asks for confirmation unless `--yes`;
  - downloads to a temporary file, verifies the sha256 and extracts safely: every member must resolve inside the target directory, and links and absolute paths are rejected;
  - moves the result into place atomically;
  - is idempotent: an existing verified directory is left alone.
  - The provisioning plan lists these archives when a sherpa backend is selected, so the containerised setup phase can fetch them with the same consent flag.
- Fetched weights live under `models_dir()` (`state/models/`, already git-ignored), where the InternVideo-Next weights also land. `.gitignore` lists `state/models/sherpa-onnx/` explicitly as well, the way it lists the InternVideo-Next directory.
- Nothing downloads at runtime. A missing model directory is a backend failure with a reason naming the setup command.

### Plumbing
- **Extras.** A new `speech-edge` extra (`sherpa-onnx>=1.13.8`). `kaine/extras.py` requires `sherpa_onnx` for Audition or Vox only when its backend is `"sherpa_onnx"`, and requires no audio extra for Vox beyond what exists.
- **Health.** The Speaches and Chatterbox dependency rows are probed only for their own backends. For `"sherpa_onnx"`, the row (`"sherpa-onnx (Moonshine)"`, `"sherpa-onnx (Kokoro)"`) builds the client and runs one real inference: 0.5 s of silence for STT, and one short word for TTS. It reports UP only if that succeeds.
- **Pre-boot and first run.** `kaine/preboot.py` and the first-run `probe_services` skip a speech service whose organ selects `"sherpa_onnx"`. Instead they check that the model directory is present.
- **Install planner.** The Termux plan lists Audition and Vox as running with `backend = "sherpa_onnx"`, with a note to install NumPy from Termux's packages (`pkg install python-numpy`) before `pip install sherpa-onnx`. The Termux path is unproven until it is installed on a device; the plan says so.
- **Tier 1 profile.** It selects `"sherpa_onnx"` for both organs and removes `vox` from `unsupported_modules`. It sets no speaker id and no voice. Tier 0 is unchanged.

### Docs honesty
`docs/deployment-tiers.md`, `config/profiles/tier0.toml` and `tier1.toml` stop describing whisper.cpp, Piper, ONNX vision and ONNX embeddings as selectable "staged seams". The sherpa-onnx speech path is described as shipped; those others are described as not built.

## Risks
- **Termux wheel resolution** is only a few weeks old upstream. The implementation is verified on the desktop, where the package and models are installed and real inference is exercised. On-device installation on the Pixel 6a is a separate operator step, recorded in the tasks as not done until it is done.
- **Latency on small hosts** is unmeasured. The desktop numbers are recorded in the PR. The phone numbers wait for the device.
- **Voice continuity:** the preset Kokoro voice differs from the Chatterbox voice. This is disclosed. Choosing a being's voice remains an operator decision.
