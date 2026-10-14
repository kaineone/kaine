## ADDED Requirements

### Requirement: Vocal picks a shipped default voice
When no voice is configured, the vocal module SHALL pick a voice from the list the speech engine itself ships and SHALL NOT use a voice name written into KAINE's code or a voice file supplied by the project. An explicit voice SHALL win: `predefined_voice_id` (Chatterbox) or `sherpa_speaker_id` (Kokoro) first, then `[vocal].default_voice`, which SHALL name a voice in the engine's list. Otherwise the module SHALL keep the voices whose gender matches `[vocal].voice_gender` (`"any"`, `"female"` or `"male"`, default `"any"`) when the engine's list makes gender knowable, and SHALL take the first of them in sorted order of their names. With Chatterbox the module SHALL read the list from the server's `/get_predefined_voices` at startup; the server reports no gender, so a `"female"` or `"male"` preference SHALL be logged as not applicable and the pick SHALL be made from all voices. With Kokoro the module SHALL read the speaker names of the pinned model from the speech manifest and SHALL take the gender from the second letter of each name's prefix. The module SHALL log the chosen voice once at startup. The vocal module SHALL stay off in the shipped configuration and in the `thesis_test` profile.

#### Scenario: Chatterbox with no voice configured
- **WHEN** the vocal module starts with the Chatterbox backend, `predefined` mode and no `predefined_voice_id` or `default_voice`, and the server lists `Olivia.wav`, `abigail.wav` and `Henry.wav` in that order
- **THEN** every synthesis request carries `predefined_voice_id = "abigail.wav"`, the same on every start, and the chosen voice is logged once

#### Scenario: A gender preference with Chatterbox
- **WHEN** `voice_gender = "male"` and no voice is configured under the Chatterbox backend
- **THEN** the module logs that the server reports no gender and picks the first voice of the whole list

#### Scenario: Kokoro maps the preference to a preset speaker
- **WHEN** the sherpa-onnx backend starts with no `sherpa_speaker_id` and the speaker table `af`, `af_bella`, `am_adam`, `bf_emma`, `bm_george`
- **THEN** `voice_gender = "any"` and `"female"` give speaker 0 (`af`), and `"male"` gives speaker 2 (`am_adam`)

#### Scenario: An explicit voice wins
- **WHEN** `predefined_voice_id`, `sherpa_speaker_id` or a `default_voice` that the engine ships is set
- **THEN** that voice is used, whatever `voice_gender` says, and a configured `predefined_voice_id` causes no query to the server

### Requirement: No voice degrades the vocal module to silence
When the engine's list cannot be read, is empty, does not contain `default_voice`, or has no voice of the requested gender, the vocal module SHALL log one line that names the problem and the key to set, SHALL record a backend failure for the health surface, and SHALL stay silent: it SHALL play nothing and SHALL publish at most one `vocal.synthesized` failure event every 60 seconds. No exception SHALL reach the cognitive cycle.

#### Scenario: Chatterbox unreachable at startup
- **WHEN** no voice is configured and `/get_predefined_voices` cannot be reached
- **THEN** `initialize()` returns normally, a backend failure is recorded for `vocal`, no audio is played, and an utterance yields a `vocal.synthesized` event with `success = false` and an error naming the missing voice

#### Scenario: An empty voice list
- **WHEN** the server answers `/get_predefined_voices` with an empty list
- **THEN** the module is silent and the logged line says the server lists no voices and names `[vocal].predefined_voice_id` and `[vocal].default_voice`

#### Scenario: No Kokoro speaker of the requested gender
- **WHEN** the speaker table has no name with the requested gender, or `default_voice` names no speaker in it
- **THEN** the sherpa-onnx backend fails to build, the failure is recorded for `vocal`, and the vocal module is disabled without stopping the boot
