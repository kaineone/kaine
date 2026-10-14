## Why

The shipped `[vocal]` section leaves `predefined_voice_id` unset, because a voice filename is operator-local. With `backend = "chatterbox"` an enabled vocal module therefore cannot speak: the Chatterbox server answers every `/tts` request with 400 ("Missing 'predefined_voice_id'"). The setup wizard makes the same assumption from the other side and turns the vocal module off when no voice id is given.

Both speech engines ship voices of their own. The Chatterbox TTS server ships a set of predefined voices in its `voices/` directory and lists them at `GET /get_predefined_voices`. The Kokoro model that KAINE pins for the sherpa-onnx backend ships eleven preset speakers whose names encode a gender. The operator approved (2026-10-12) that the vocal module picks one of these shipped voices when none is configured, with an optional gender preference, and that the project never adds voice files of its own.

## What Changes

- Two new `[vocal]` keys:
  - `voice_gender`: `"any"` (the default), `"female"` or `"male"`.
  - `default_voice`: an optional name of a voice the engine ships, a Chatterbox voice filename or a Kokoro speaker name.
- When no voice is configured, the vocal module picks one deterministically from the engine's own list:
  - Chatterbox: at startup the module asks the server for its predefined voices and takes the first filename in sorted order. The server reports no gender, so a gender preference cannot be applied there; the module says so in its log and chooses from all voices.
  - Kokoro: the factory maps the preference to a preset speaker id through the speaker table of the pinned model, taking the first speaker name in sorted order whose gender matches.
- An explicit choice wins over the automatic one. `predefined_voice_id` and `sherpa_speaker_id` keep their meaning and take precedence; `default_voice` comes next.
- The module logs the chosen voice once at startup.
- No voice name is hard-coded. If the engine's list is empty, unreachable, or has no voice that matches, the module logs one clear operator line, records a backend failure for the health surface, and stays silent. The cognitive cycle never crashes on it.
- The speech manifest records the Kokoro speaker table for the pinned `kokoro-en` archive.
- The setup wizard no longer turns the vocal module off when no Chatterbox voice id is given, and it reads the server's voice list in the format the server returns (a list of objects with `display_name` and `filename`).
- The vocal module stays off in the shipped configuration and in the `thesis_test` profile.
- Letting the entity choose its voice is designed as a follow-up only (design section "Follow-up: the entity's own choice"); nothing of it ships here.

## Capabilities

### Modified Capabilities

- `vocal`: the vocal module picks a shipped default voice when none is configured, filtered by an optional gender preference, and degrades to silence with a clear message when it cannot.

## Impact

- `kaine/modules/vocal/voices.py` (new), `kaine/modules/vocal/client.py`, `kaine/modules/vocal/module.py`, `kaine/boot/factories/vocal.py`, `kaine/speech_manifest.py`, `kaine/setup/__main__.py`, `kaine/setup/wizard_steps.py`.
- `config/kaine.toml` (`[vocal]` comments and the two keys), `docs/09-modules/vocal.md`, `docs/appendix-a-configuration/modules.md`.
- Tests with fake servers and fake model metadata.
- No voice files enter the repository. The research configuration is unchanged.
