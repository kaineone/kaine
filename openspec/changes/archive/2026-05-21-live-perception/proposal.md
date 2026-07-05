## Why

KAINE today can *process* one-shot audio/video payloads but can't *sense*
its surroundings on its own. There's no microphone capture loop and no
camera capture loop — the existing `audio_in` and `topos` modules accept
bytes/images you hand them and stop there.

This change gives KAINE eyes and ears: live, ephemeral streams of mic and
camera input that pass through the existing perception modules to the
brain. The framing matters — eyes and ears don't archive their inputs.
They transduce live signal to the cortex, which then forms perceptions.
The brain remembers the processed perception (transcribed words, frame
embeddings), but the raw stream itself is in-memory only and discarded
after processing.

The operator-facing controls and on-air indicator live on the existing
Nexus diagnostics UI (Phase 8). Toggle via `POST /diagnostics/perception/
toggle`; banner shown on both the conversation and diagnostics surfaces
while either stream is active.

## What Changes

- New `kaine/modules/audio_in/live.py`: `LiveMicrophone` class. Uses
  `sounddevice.InputStream` (background thread) + `webrtcvad` to detect
  utterance boundaries. On utterance end, wraps the PCM buffer as a WAV
  with `wave.open(io.BytesIO(), 'wb')` — never a file path — and calls
  `AudioInput.process_audio(wav_bytes, sample_rate, "live_mic")`.
- New `kaine/modules/topos/live.py`: `LiveCamera` class. Polls
  `cv2.VideoCapture(device)` in a background thread at `capture_interval_s`,
  converts BGR→RGB to a `PIL.Image`, awaits `Topos.process_frame(image)`.
  Habituation + change detection inside Topos already throttle output for
  static scenes.
- New `kaine/perception_state.py`: tiny module that reads/writes
  `state/perception/runtime.json` (capture-active booleans + ISO
  timestamps) and `state/perception/desired.json` (operator-requested
  state from the Nexus toggle). Both files contain ZERO sensory content.
- Wire `LiveMicrophone` into `AudioInput.__init__` + `initialize`/
  `shutdown`. Wire `LiveCamera` into `Topos` the same way.
- `kaine/nexus/perception.py`: `GET /diagnostics/perception.json` returns
  active/desired/available booleans; `POST /diagnostics/perception/toggle`
  writes `desired.json`; the perception tasks poll it and start/stop
  themselves to match.
- New `kaine/nexus/templates/_perception_banner.html` partial, included
  by `conversation.html` and `diagnostics.html`. Red bar when audio or
  video is active.
- pyproject extras: `audio` (sounddevice + webrtcvad), `vision`
  (opencv-python-headless). Both imported lazily inside `initialize()` so
  missing extras fail loud only when capture is actually enabled.
- `config/kaine.toml` adds capture keys to `[audio_in]` and `[topos]`;
  both default `capture_enabled = false`. `kaine/boot.py` forwards the
  new keys.
- Tests: `test_audio_in_live.py` (FakeMicrophoneStream + FakeVAD),
  `test_topos_live.py` (FakeVideoSource), `test_perception_state.py`,
  `test_nexus_perception.py`, and the load-bearing
  `test_zero_persistence_invariant.py` that runs both streams against
  fakes and scans disk for any audio/video MIME signature or extension.

## Capabilities

### New Capabilities

- `live-perception` — opt-in always-on microphone and camera streams
  that feed the existing perception modules; carries the load-bearing
  zero-persistence invariant for raw sensory data and the on-air
  indicator contract for the Nexus surfaces.

### Modified Capabilities

- `nexus-diagnostics` — adds the perception card + toggle endpoints +
  on-air banner partial. The privacy filter remains the load-bearing
  enforcement point for transcription content on the diagnostics SSE.

## Impact

- **New deps:** optional extras only. Production install (`pip install
  -e .`) is unaffected. Operators who want live perception run
  `pip install -e .[audio,vision]`.
- **No core module changes.** `AudioInput` and `Topos` gain new init
  kwargs but their existing entry points are unchanged.
- **Zero raw-sense-data persistence.** Enforced by code (no file-path
  arguments on the audio/video paths) AND by the load-bearing
  invariant test.
- **`state/perception/`** is gitignored; the runtime/desired files are
  created at boot.
- Tag `v1.2-perception` after merge.
