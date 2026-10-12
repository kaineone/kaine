## 1. Design

- [x] 1.1 Research what the Chatterbox TTS server and the pinned Kokoro model ship, how they list it, and whether gender is knowable; cite the sources in design.md
- [x] 1.2 Proposal, design, tasks, delta spec on `vox`, and a roadmap row

## 2. Selection

- [x] 2.1 `kaine/modules/vox/voices.py`: the gender values, the Kokoro name-to-gender rule, the parser for the Chatterbox voice list, and the deterministic selection for both engines with one-line errors
- [x] 2.2 `SpeechModel.speakers` in the speech manifest, filled for `kokoro-en` from the sherpa-onnx speaker map
- [x] 2.3 `ChatterboxClient.list_voices()` reads `GET /get_predefined_voices`
- [x] 2.4 The vocal module resolves a Chatterbox voice in `initialize()` when none is configured, logs it once, and on failure records a backend failure and stays silent
- [x] 2.5 The vocal factory accepts `voice_gender` and `default_voice`, rejects an unknown gender, and maps the preference to a Kokoro speaker id when `sherpa_speaker_id` is absent
- [x] 2.6 The setup wizard keeps the vocal module on without a Chatterbox voice id and reads the server's voice objects by filename

## 3. Tests

- [x] 3.1 Selection is deterministic whatever order the server lists its voices in
- [x] 3.2 The gender filter for Kokoro, and the logged fallback to all voices for Chatterbox
- [x] 3.3 An explicit voice wins (`predefined_voice_id` with no server query, `sherpa_speaker_id`, `default_voice`)
- [x] 3.4 An empty, unreachable or non-matching list degrades with a clear message and no exception, and an utterance then publishes a failure event and plays nothing
- [x] 3.5 Kokoro mapping through a fake speaker table, and the factory's failure path
- [x] 3.6 The vocal module stays disabled in the shipped config and the `thesis_test` profile

## 4. Docs and config

- [x] 4.1 `[vox]` comments in `config/kaine.toml` and the two keys
- [x] 4.2 `docs/09-modules/vocal.md` and the `[vox]` table in `docs/appendix-a-configuration/modules.md`

## 5. Follow-up: the entity's own choice (separate change, not in this PR)

- [ ] 5.1 Answer the open questions in design.md ("Follow-up: the entity's own choice") with the operator and the Guardians
- [ ] 5.2 Design the consent and choice protocol once the self-model module is released and the maturity assessment that opens it is defined
