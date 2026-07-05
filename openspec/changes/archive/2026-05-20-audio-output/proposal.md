## Why

`docs/kaine-paper.md` §3.4 frames audio output as "expressive
text-to-speech engine whose vocal characteristics are driven by
Thymos's current affective state, so that the system's voice reflects
its actual internal emotional condition rather than producing a
neutral reading." Build prompt §5.3 names Chatterbox as the
already-installed TTS server. Phase 5.3 wires Chatterbox's
`/tts` endpoint to Lingua's external speech stream and to Thymos's
dimensional state.

## What Changes

- Introduce `kaine.modules.audio_out` package split four files:
  - `client.py` — `TTSClient` protocol + `ChatterboxClient` default
    (httpx async POST to `http://127.0.0.1:8883/tts`) + `FakeTTSClient`
    for tests.
  - `mapping.py` — `affect_to_chatterbox(state)` pure function mapping
    a `DimensionalState` to Chatterbox's `temperature`,
    `exaggeration`, `cfg_weight`, `speed_factor`. Linear interpolation
    inside documented [floor, ceiling] bands; pure Python.
  - `module.py` — `AudioOutput(BaseModule)`. Subscribes to
    `lingua.external` (the stream Lingua publishes user-facing speech
    to in Phase 5.2) and optionally to `thymos.state` (for the
    affect-driven expressivity). On each lingua.external event,
    synthesizes audio and publishes `audio.out.synthesized` with
    byte-count + parameters (no audio bytes on the bus event).
    Writes the audio to a configurable output sink (default:
    `state/audio_out/` directory).
- `[audio_out]` block in `config/kaine.toml`: Chatterbox URL,
  default voice, output sink path, baseline params (when no Thymos
  state is available), publish interval, salience.
  `modules.audio_out = false`.
- Tests use `FakeTTSClient` returning deterministic byte blobs. Opt-in
  real-Chatterbox test guarded by `KAINE_AUDIO_OUT_RUN_REAL=1`.

## Capabilities

### New Capabilities

- `audio-output`: Chatterbox TTS integration. Owns the HTTP client,
  the Thymos-affect → Chatterbox-params mapping, the
  `lingua.external` consumer task, the synthesized-audio sink.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `lingua` (consumes
  its external stream), optionally `thymos` (consumes its
  state). All shipped.
- **Repo:** adds `kaine/modules/audio_out/*.py`, `tests/test_audio_out_*`,
  updates `pyproject.toml` packages list, `config/kaine.toml`,
  gitignored `state/audio_out/`.
- **Operator action:** the Chatterbox TTS server (already installed
  on this host at `~/.local/share/elite-tools/src/Chatterbox-TTS-Server/`)
  must be running for synthesis to actually produce audio. Without
  it, AudioOutput logs warnings and skips synthesis but doesn't
  crash.
- **No runtime impact** on the cycle. AudioOutput is registered in
  code paths but not auto-added to ModuleRegistry; first boot
  decides.
