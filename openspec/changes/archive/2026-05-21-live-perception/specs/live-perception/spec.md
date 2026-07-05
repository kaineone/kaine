## ADDED Requirements

### Requirement: Zero raw-sense-data persistence
The live perception path SHALL NOT write any raw audio or video data to
disk under any circumstance. Raw PCM samples, in-memory WAV blobs, and
camera frames SHALL live in process memory only and SHALL be released
after the parent module's `process_audio` or `process_frame` call
returns. The repository SHALL ship
`tests/test_zero_persistence_invariant.py` that activates both perception
streams against fakes and scans every relevant disk path for files with
audio/video MIME signatures or extensions; the test SHALL fail if any
such file appears.

#### Scenario: WAV path never uses a file argument
- **WHEN** an operator runs `git grep "wave.open" kaine/modules/audio_in/`
- **THEN** every match passes an `io.BytesIO` instance (not a file
  path) as the first argument

#### Scenario: Camera path never writes images
- **WHEN** an operator runs `git grep -E "cv2\.(imwrite|VideoWriter)" kaine/`
- **THEN** the search returns no matches

#### Scenario: Invariant test fails when leak introduced
- **WHEN** the live perception streams run for several seconds against
  fake hardware
- **THEN** the only new files anywhere on disk are
  `state/perception/runtime.json`, `state/perception/desired.json`, and
  standard log lines containing `capture_started` / `capture_stopped`
  state-transition strings — no `.wav`, `.pcm`, `.raw`, `.png`, `.jpg`,
  `.mp4`, or `.webm` files appear

### Requirement: Capture defaults off in shipped config
The shipped `config/kaine.toml` SHALL set
`[audio_in].capture_enabled = false` and
`[topos].capture_enabled = false`. Enabling capture SHALL be a
deliberate per-module opt-in by the operator.

#### Scenario: Default config does not open the microphone
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** `[audio_in].capture_enabled` is `false`

#### Scenario: Default config does not open the camera
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** `[topos].capture_enabled` is `false`

### Requirement: Optional deps gate fails loud at initialize
The perception classes SHALL lazy-import `sounddevice` / `webrtcvad`
(audio) and `cv2` (video) inside `initialize()`. If `capture_enabled =
true` but the corresponding optional extras are not installed,
`initialize()` SHALL raise `PerceptionUnavailableError` with a message
naming the extras group to install. The parent module SHALL log the
error and continue running without live perception.

#### Scenario: Missing audio extras raise clearly
- **WHEN** `[audio_in].capture_enabled = true` and `sounddevice` is not
  importable
- **THEN** `LiveMicrophone.initialize()` raises
  `PerceptionUnavailableError` whose message contains
  `kaine[audio]`

### Requirement: State-transition logging only
The perception loops SHALL emit log lines for state transitions only:
`capture_started`, `capture_stopped`, `utterance_started`,
`utterance_ended`, `frame_capture_failed`. Log lines SHALL NOT include
the transcribed text, audio bytes, or frame contents.

#### Scenario: Logs do not contain transcribed text
- **WHEN** the perception path captures an utterance whose Speaches
  transcription is "the access code is 1234"
- **THEN** no log line emitted by `kaine.modules.audio_in.live` or
  `kaine.modules.topos.live` contains the substring "1234" or the
  transcribed text

### Requirement: Runtime state file written atomically
The perception loops SHALL write `state/perception/runtime.json` on
every start and stop via write-temp-then-rename so concurrent readers
never see a partial file. The file SHALL contain ONLY operational state
booleans and ISO-8601 timestamps — no sensory content.

#### Scenario: Atomic write
- **WHEN** `update_audio_runtime(active=True)` runs
- **THEN** no `.tmp` file remains in `state/perception/` after the call
  returns and `runtime.json` parses as valid JSON

### Requirement: Nexus toggle mutates desired state, perception polls it
The toggle endpoint at `POST /diagnostics/perception/toggle` SHALL accept a body of
`{"surface": "audio"|"video", "active": bool}` and write
`state/perception/desired.json`. The perception loops SHALL poll this
file every poll interval (≤1 second for audio, `capture_interval_s` for
video) and start or stop themselves to match the desired state.

#### Scenario: Toggle off stops the stream
- **WHEN** the audio stream is active and `POST /diagnostics/perception/
  toggle` is called with `{"surface": "audio", "active": false}`
- **THEN** within one poll interval, `LiveMicrophone` stops the
  underlying `sounddevice.InputStream` and updates
  `runtime.json` with `audio_live_active = false`

### Requirement: On-air banner appears on both surfaces while active
Nexus SHALL include a banner partial on both the conversation route at `/`
and the diagnostics route at `/diagnostics` that renders a red on-air
indicator whenever `runtime.json` reports any perception stream active.
The banner SHALL show which streams are on (microphone, camera, or
both).

#### Scenario: Banner visible on conversation page
- **WHEN** the audio stream is active and an operator opens `/`
- **THEN** the rendered HTML contains the substring "microphone on"
  inside an element with class `live-perception-banner`

#### Scenario: Banner visible on diagnostics page
- **WHEN** the video stream is active and an operator opens
  `/diagnostics/`
- **THEN** the rendered HTML contains the substring "camera on" inside
  an element with class `live-perception-banner`

### Requirement: PrivacyFilter strips transcription text from diagnostics SSE
Transcription events flowing from the live microphone path SHALL be
stripped of their `text` and `transcription` fields before reaching any
client subscribed to the diagnostics SSE surface. This restates the
existing `nexus-privacy` boundary against the new event source.

#### Scenario: Transcription text not on diagnostics SSE
- **WHEN** the live microphone emits an `audio_in.transcription` event
  with `payload.text = "secret"`
- **THEN** the event delivered to any diagnostics-surface SSE client
  has no `text` key in its payload
