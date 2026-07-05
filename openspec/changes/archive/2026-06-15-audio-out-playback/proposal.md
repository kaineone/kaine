## Why

Audio output never reaches the speakers, and every utterance is persisted to
disk forever. Found live 2026-06-03:

- `AudioOutput._sink_audio` (`kaine/modules/audio_out/module.py:143-151`) writes
  the synthesized WAV to `state/audio_out/<ts>-<uuid>.wav` and that is the *only*
  thing done with the audio. There is **no playback path** anywhere in the
  module (no `sounddevice`, no system player), and Nexus has no audio-playback
  route either. KAINE synthesizes speech correctly (verified: Chatterbox returns
  a valid 24 kHz WAV with the configured voice) but the operator never hears it.
- Nothing ever deletes the sink files. Each is ~0.1–2 MB; at conversational
  rates this fills the disk without bound. The operator flagged this directly.

Synthesized speech is the entity's own transient utterance, not a recording to
archive. It should be played and released, consistent with the eyes-and-ears
"transducer, not recorder" posture applied to perception.

## What Changes

- `audio_out` SHALL play synthesized audio through the host's default (or a
  configured) output device by default. Playback is the primary action; the file
  sink becomes optional and off by default.
- Rendered audio SHALL NOT be persisted indefinitely. Default: **play then
  discard** (no file written). An optional bounded debug cache MAY retain a small
  number of recent clips (`retain_count`, default 0) or a byte ceiling, evicting
  oldest first; it is never unbounded.
- Self-hearing SHALL be handled **when enabled**: while a clip plays aloud and
  the live mic is capturing, the entity SHALL NOT ingest its own voice as a user
  utterance. Approach: gate `audio_in` capture (or discard transcriptions) for
  the duration of playback plus a short hangover. This complements the existing
  own-speech guard in the action policy. Suppression is configurable
  (`suppress_self_hearing`, default true for safety on open-speaker setups);
  operators using an acoustically isolated input (e.g. a headset mic, as in the
  current deployment) MAY disable it, since the mic does not capture playback.
- Playback SHALL degrade gracefully: if no output device is available or the
  audio extra is missing, log once and continue (synthesis/eventing unaffected),
  mirroring the live-perception soft-disable pattern.
- New `[audio_out]` config: `playback_enabled` (default true), `output_device`
  (default OS default), `sink_enabled` (default false), `retain_count`
  (default 0), `suppress_self_hearing` (default true), `mic_mute_hangover_ms`.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `audio-output`: adds playback through an output device as the primary sink;
  makes file persistence optional, off by default, and bounded when on; adds
  self-hearing suppression coordinated with `audio-input`; adds graceful
  degradation when no device/extra is available.
