## 1. Playback

- [x] 1.1 Add `kaine/modules/audio_out/playback.py`: `Player` protocol,
      `SoundDevicePlayer` (lazy import, in-memory WAV decode, plays on
      configured/default device), `NullPlayer`. Missing extra/device → NullPlayer
      + single warning.
- [x] 1.2 `AudioOutput` constructs a player from config; `synthesize_text` plays
      the clip via `asyncio.to_thread`, serialized so clips play in order.
- [x] 1.3 Graceful degradation: no device / no `sounddevice` → log once, continue
      (synthesis + `audio.out.synthesized` event still happen).

## 2. Retention

- [x] 2.1 Default `sink_enabled=false`: do not write; play from memory and
      release.
- [x] 2.2 When `sink_enabled=true`, prune `state/audio_out` to newest
      `retain_count` (or byte ceiling) after each write, oldest first.
- [x] 2.3 On init, log count/size of any pre-existing clips; do not auto-delete.

## 3. Self-hearing suppression (config-gated)

- [x] 3.1 audio_out marks a "speaking" window (start → end + `mic_mute_hangover_ms`)
      only when `suppress_self_hearing` is true.
- [x] 3.2 audio_in drops utterances starting within the speaking window when
      suppression is enabled; no-op when disabled (full-duplex).
- [x] 3.3 Wire the signal between modules at the cycle/boot layer (in-process
      flag/timestamp); no new bus contract unless cleaner.
- [x] 3.4 `suppress_self_hearing` default true; document that an isolated headset
      mic (current deployment) sets it false.

## 4. Config

- [x] 4.1 Add `[audio_out]`: `playback_enabled` (true), `output_device` (""),
      `sink_enabled` (false), `retain_count` (0), `suppress_self_hearing` (true),
      `mic_mute_hangover_ms`. Pass through `make_audio_out` allowed set. Shipped
      config stays all-off.

## 5. Tests

- [x] 5.1 Fake player records played clips; `synthesize_text` plays once per
      utterance; clips serialize in order.
- [x] 5.2 `sink_enabled=false` writes no file; `=true` prunes to `retain_count`.
- [x] 5.3 Missing device/extra → NullPlayer, no raise, event still published.
- [x] 5.4 Self-hearing: an utterance starting inside the speaking window is
      dropped by audio_in; one starting after the hangover is kept.

## 6. Live validation (operator-supervised)

- [x] 6.1 Boot full stack; speak; **hear** the response in the configured voice.
- [x] 6.2 Confirm `state/audio_out` does not grow unbounded (empty by default).
- [ ] 6.3 Confirm the entity does not transcribe its own spoken output as a new
      user utterance.

## 7. Docs

- [x] 7.1 Update audio_out module docs + `FIRST_BOOT.md` perception section:
      playback on by default, play-and-release, retention is opt-in and bounded,
      half-duplex behavior while speaking.
