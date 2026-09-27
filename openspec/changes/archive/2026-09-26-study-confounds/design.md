# Design — `study-confounds`

## Source labels

- `boot.py` builds `LiveMicConfig`. It sets `source_label` from the perception-feed mode when the audio stream is a feed: `playlist`, `seeded`, `womb` or `screen`. With no feed (a real device) it stays `live_mic`. Audition already stamps `source_label` on `audition.emotion`, `audition.transcription` and its perception events.

## Empatheia

- New config `[empatheia].operator_sources`, a list of strings, default `["live_mic", "microphone", "remote"]`.
- `_agent_for(event)` returns `speaker_label` when `payload["source_label"]` is in `operator_sources`, or is missing (older producers, so behaviour is unchanged), and `media:<source_label>` otherwise.
- `_handle_emotion` and `_handle_transcription` use it.
- An agent id is opaque: it never holds content, so zero raw-sense-data persistence holds.

## Volition

- `_user_utterance(event)` also requires `payload.get("source_label")` to be in the operator sources, or missing. `Volition` and `DriveBiasedActionSelectionPolicy` receive the operator-source set from config, defaulting to the same list.
- Speech from other channels is unchanged in the workspace; only the addressed-to-me inference changes.

## Vox in the womb

- `Vox.set_dormant(bool)`. While dormant, Vox renders nothing to the player. It logs a debug line per suppressed utterance, so a count is visible, and publishes nothing new.
- The cycle entrypoint sets Vox dormant with Mundus when gestating. The gate runner's birth hook activates it, just before Mundus.
- The basis is physical, not cognitive: the womb has no air medium. Lingua, and so inner speech, is untouched.
