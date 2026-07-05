# Design — Audio output playback and bounded retention

## 1. Current behavior

`synthesize_text` → `_sink_audio` writes bytes to `state/audio_out/`. That is the
terminus. No playback, no eviction. `_publish_event` then emits
`audio.out.synthesized` (metadata only — correct, keep). Affect→voice mapping
(`affect_to_chatterbox`) already modulates exaggeration/cfg/temperature from
Thymos state and is unaffected by this change.

## 2. Playback

- Add a `Player` abstraction (`kaine/modules/audio_out/playback.py`) with a real
  `SoundDevicePlayer` (lazy `import sounddevice`, decode WAV → ndarray, play on
  the configured/default device) and a `NullPlayer` (no device / extra missing /
  `playback_enabled=false`). Construction mirrors the live-perception
  `PerceptionUnavailableError` soft-disable: a missing `sounddevice`/PortAudio
  becomes `NullPlayer` + one warning, never a crash.
- `synthesize_text` flow becomes: synthesize → (optional bounded sink) →
  **play** → publish event. Playback is awaited off the event loop
  (`asyncio.to_thread`) so the cycle is not blocked.
- Output format: Chatterbox returns WAV; decode in-memory (stdlib `wave` +
  numpy) — no temp file required for playback.

## 3. Retention

- Default `sink_enabled=false`: nothing is written; the WAV is played from memory
  and released.
- When `sink_enabled=true`, retention is bounded: after each write, prune
  `state/audio_out` to the newest `retain_count` files (or a byte ceiling),
  deleting oldest first. `retain_count=0` with `sink_enabled=true` means "write
  then immediately prune to zero" — effectively transient; the meaningful use is
  a small N for debugging.
- One-time migration nicety: on init, if the sink dir holds clips from prior
  unbounded behavior, log their count/size (do not auto-delete operator data).

## 4. Self-hearing suppression

Playing aloud with a live mic risks the entity transcribing its own voice as a
user utterance (a feedback loop the action policy's own-speech guard only
partially blocks, since the *transcription* would be attributed to the user
source).

- When `suppress_self_hearing` is true, during playback (plus
  `mic_mute_hangover_ms`) suppress audio-in ingestion. Coordinate via the
  existing perception-state seam: audio_out signals a "speaking" window;
  `audio_in` drops utterances that start within it. Prefer dropping at the
  audio_in boundary over muting the OS device, so other audio is unaffected.
- The flag exists because suppression is only needed when the mic can hear the
  speakers. With an acoustically isolated input — e.g. the operator's headset mic
  — playback never reaches the mic, so `suppress_self_hearing=false` keeps the
  entity fully duplex (it can be spoken to while speaking). Default stays true so
  an open-speaker install is safe out of the box; a future first-run setup
  wizard is the natural place to ask which the operator has.
- Keep it simple and local: a shared in-process flag / timestamp the cycle wires
  between the two modules, not a new bus contract, unless a bus signal proves
  cleaner during implementation.

## 5. Privacy / posture

Synthesized speech is the entity's own output, not raw sense data, so this is not
a perception-persistence question — but the same "transducer, not recorder"
instinct applies: default to play-and-release, make any retention explicit,
bounded, and operator-chosen. No content is logged beyond the existing
metadata-only `audio.out.synthesized` event.

## 6. Risks

- **Device contention / wrong sink.** `output_device` lets the operator pin the
  device; default OS device matches how the operator already hears other audio.
- **Latency of playback blocking the consumer loop.** Mitigated by
  `to_thread`; the consumer can continue reading while a clip plays, but clips
  SHOULD play in order — serialize playback with an async lock/queue.
- **Half-duplex feel.** With self-hearing suppression the entity is effectively
  half-duplex (won't listen while speaking). Acceptable for v1; full-duplex with
  acoustic echo cancellation is future work.

## 7. Out of scope

- Acoustic echo cancellation / full-duplex.
- Streaming/chunked playback as audio synthesizes (single-shot for now).
- Browser-side playback in Nexus.
