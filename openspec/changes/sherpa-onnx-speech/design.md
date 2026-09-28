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
  - **Audition.** Speech recognition is one of Audition's faculties; hearing, acoustic salience, vocal emotion and womb audio do not depend on it.
    - With `transcription_enabled = false` the STT backend is not resolved at all: no model loads, and the extras check does not require `sherpa-onnx`.
    - With transcription on, a sherpa factory failure (missing or corrupt model files) is recorded with `record_backend_failure` and logged. Audition is still registered, with transcription disabled, and the Nexus sherpa-onnx row reports DOWN with the reason.
  - **Vox.** Speech output is Vox's only faculty, so a sherpa factory failure is recorded, and the module is not registered.
  - The backend value is normalised (stripped, lowercased) once. Every disclosure (`backend`, `prosody_applied`, voice label, failure `model`) is derived from the backend that actually resolved.
  - **Loading off the event loop.** Construction validates the model files only. The sherpa model loads in the engine's worker thread through an async `warm_up()`, which the module awaits in `initialize()`. Neither a boot nor a Spot restart stalls the event loop on a model load.
  - **A failed warm-up degrades; it never aborts the boot.** A corrupt model or an invalid speaker id raises from `warm_up()`, and the module catches it in `initialize()`:
    - Audition disables transcription.
    - Vox marks its synthesiser unavailable and stays registered.
      - While dormant it publishes nothing, as always.
      - Otherwise, at most once per 60 s of entity time, it publishes `vox.synthesized` with `success = false`, the reason, and baseline salience, without calling the engine.
      - The Hypnos ignition audit counts a failed `vox.synthesized` as a failed realisation, not a realised utterance.
    - Both record the failure with `record_backend_failure` and log it.
  - **Native-exit protection.** sherpa-onnx calls `exit()` from native code on a malformed `tokens.txt`, and no Python exception can catch that. So before any native load the engines:
    - require a model directory whose `.verified` marker matches the manifest (sizes of every file) and whose `tokens.txt` matches the sha256 recorded at install;
    - parse `tokens.txt` in Python exactly as sherpa-onnx does: a whitespace split giving either one field (the id of the space token, at most once) or two fields (symbol and id). Duplicate symbols are allowed, because the genuine Moonshine files contain them.

    A directory that fails either check is refused with an actionable error. A custom `sherpa_model_dir` must therefore be populated by `python -m kaine.setup.speech_models --root`.
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
| `kokoro-en` (TTS default) | `tts-models/kokoro-int8-en-v0_19.tar.bz2` | 103,248,205 B | `c9f0dd393615805b0bab050c340834d5e684e732aec91c0e860cd30e982c08bd` | Apache-2.0 (model); GPL-3.0-or-later (bundled espeak-ng-data) |

  - An archive whose digest differs is rejected. The archives contain only regular files and directories.
  - A successful install writes a `.verified` marker holding the archive's sha256 and each required file's size. `is_installed` requires the marker to match, so a truncated or resized install is re-fetched (a same-size edit is not detected; the sha256 covers the archive, not the extracted files).
  - A symlinked or dangling target is replaced, never followed.
  - On Python builds without `tarfile.data_filter` (before 3.11.4), extraction writes each validated regular file itself.
  - **Licence note.** Kokoro's grapheme-to-phoneme step uses espeak-ng: the archive bundles espeak-ng-data, and the sherpa-onnx package builds in espeak-ng. Both are GPL-3.0-or-later. The consent line names both licences, and the operator decides. This is recorded for the pending CAL legal review. KAINE does not redistribute either; the operator installs them.
  - Verified on the development host with sherpa-onnx 1.13.8 imported from a scratch directory (not installed): Kokoro speaker 0 synthesised "The quick brown fox jumps over the lazy dog." (24 kHz, 11 speakers, 1.3 s cold), and Moonshine base transcribed it back exactly in 40 ms. Half a second of silence transcribes to an empty string.
- `python -m kaine.setup.speech_models [--stt ID] [--tts ID] [--yes]`:
  - prints each archive's name, size and licence;
  - asks for confirmation unless `--yes`;
  - downloads to a temporary file, verifies the sha256 and extracts safely: every member must resolve inside the target directory, and links and absolute paths are rejected;
  - moves the result into place atomically;
  - is idempotent: an existing verified directory is left alone.
  - The provisioning plan lists these archives when a sherpa backend is selected. The containerised setup phase fetches them only with an explicit speech-consent flag (`--speech-models` or `KAINE_PROVISION_SPEECH_MODELS=1`), and prints each archive's name, size and licence before downloading.
- Fetched weights live under `models_dir()` (`state/models/`, already git-ignored), where the InternVideo-Next weights also land. `.gitignore` lists `state/models/sherpa-onnx/` explicitly as well, the way it lists the InternVideo-Next directory.
- Nothing downloads at runtime. A missing model directory is a backend failure with a reason naming the setup command.

### Plumbing
- **Extras.** A new `speech-edge` extra (`sherpa-onnx>=1.13.8`). `kaine/extras.py` requires `sherpa_onnx` for Audition or Vox only when its backend is `"sherpa_onnx"`, and requires no audio extra for Vox beyond what exists.
- **Health.** The Speaches and Chatterbox dependency rows are probed only for their own backends. For `"sherpa_onnx"`, the row (`"sherpa-onnx (Moonshine)"`, `"sherpa-onnx (Kokoro)"`) builds the client and runs one real inference: 0.5 s of silence for STT, and one short word for TTS. It reports UP only if that succeeds.
  - The probe is **single-flight**. One background load per model runs to completion even when the prober's own timeout cancels the caller, and later calls report DEGRADED "probe in progress" until it finishes.
  - **Isolation.** The probe's load and inference run in a child Python process with a 300 s limit, so neither a native `exit()` nor a hung load can take Nexus or pre-boot down. On timeout the child is killed and the row reports DOWN.
  - **Fingerprint.** It covers only the required files and the `.verified` marker, and is computed off the event loop.
  - **Pre-boot waits.** The one-shot pre-boot check lets an in-flight load finish, up to the same 300 s bound, instead of reporting "in progress" as a failure.
  - **Normalisation.** The health configuration normalises backend values exactly as boot does.
  - A success is remembered while the model files are unchanged (size and mtime re-checked on every read). A failure is retried after 60 s. A slow small host therefore never stacks model loads.
- **Pre-boot and first run.** `kaine/preboot.py` and the first-run `probe_services` skip a speech service whose organ selects `"sherpa_onnx"`. Instead they check that the model directory is present.
- **Install planner.** The Termux plan lists Audition and Vox as running with `backend = "sherpa_onnx"`, with a note to install NumPy from Termux's packages (`pkg install python-numpy`) before `pip install sherpa-onnx`. The Termux path is unproven until it is installed on a device; the plan says so.
- **Tier 1 profile.** It selects `"sherpa_onnx"` for both organs and removes `vox` from `unsupported_modules`. It sets no speaker id and no voice. Tier 0 is unchanged.

### Docs honesty
`docs/deployment-tiers.md`, `config/profiles/tier0.toml` and `tier1.toml` stop describing whisper.cpp, Piper, ONNX vision and ONNX embeddings as selectable "staged seams". The sherpa-onnx speech path is described as shipped; those others are described as not built.

## Risks
- **Termux wheel resolution** is only a few weeks old upstream. The implementation is verified on the desktop, where the package and models are installed and real inference is exercised. On-device installation on the Pixel 6a is a separate operator step, recorded in the tasks as not done until it is done.
- **Latency on small hosts** is unmeasured. The desktop numbers are recorded in the PR. The phone numbers wait for the device.
- **Voice continuity:** the preset Kokoro voice differs from the Chatterbox voice. This is disclosed. Choosing a being's voice remains an operator decision.
