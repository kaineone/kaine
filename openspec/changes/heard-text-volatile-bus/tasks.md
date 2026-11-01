## 0. Prerequisites

- [x] 0.1 Ruling: heard text and the entity's own utterance text travel only on the never-persisted instance (architecture decisions of 2026-11-01, item 2; `latent-content-privacy` open question 1, ruled B)
- [ ] 0.2 `latent-content-privacy` PR 3 merged: the volatile instance, the companion helpers with a declared field set, the companion-first ordering and the `companion` envelope field, `[privacy].companion_stream_maxlen`, the shared boot check and budget row
- [ ] 0.3 For PR 3 of this change: the `operator-speech-as-perception` PR that removes heard words from intent `about` fields merged

## 1. The field set and the bus (PR 1)

- [ ] 1.1 `kaine/faithful/external_input.py`: `split_spoken_text`, `SPOKEN_TEXT_METADATA_KEYS = {"source_label", "model", "backend"}` (each commented with why it holds no words), `SPOKEN_TEXT_RULE_VERSION = 1`; the module docstring states the rule beside the heard rule
- [ ] 1.2 `text_chars` and `text_words` for a diverted top-level `text`; an event with nothing to divert is published unchanged
- [ ] 1.3 `kaine/bus/client.py`: every main-bus publish applies the split through the companion helper with this field set declared
- [ ] 1.4 `kaine/cycle/engine.py` `_snapshot_to_payload`: each selected member split, its own companion reference recorded as `companion`, no second copy
- [ ] 1.5 `kaine/modules/base.py` `_snapshot_from_payload`: joins members' companion entries for modules declaring `reads_spoken_text`, and only for them
- [ ] 1.6 Producer declarations: the language module always, the audition module when `transcription_enabled`; the companion streams of `audition.out`, `embodiment.out`, `language.external`, `language.internal`, `language.out`, `episodic_memory.out`; the preboot "Bus budget" row adds them
- [ ] 1.7 Tests in `tests/test_spoken_text_bus.py`: `test_split_transcription`, `test_split_error_transcription`, `test_split_chat_unknown_string_diverted`, `test_split_language_event_all_three_fields`, `test_split_replay_text`, `test_event_without_words_unchanged`, `test_counts`, `test_main_publish_holds_no_words`, `test_broadcast_member_references_not_copies`, `test_decoder_joins_only_declaring_modules`, `test_boot_refused_without_volatile_instance_when_language_on`

## 2. Consumers (PR 2)

- [ ] 2.1 Language module declares `reads_spoken_text`; heard turn and residual redaction on joined words; missing entry renders "Speech heard but indistinct."
- [ ] 2.2 Episodic memory declares `reads_spoken_text`; heard rule on the joined event; own speech kept with its words, `<words unavailable>` when missing
- [ ] 2.3 Vocal module and embodiment module read the text from the companion entry of `language.external` and the speech stream; vocal publishes a failed `vocal.synthesized` with `error: "words unavailable"` when missing
- [ ] 2.4 Remote bridge `_transcript_loop` joins; a missing entry skips the line
- [ ] 2.5 `kaine/evaluation/_base.py`: a join option on `StreamSubscriberObserver`; `external_utterance_log`, `ab_divergence` and `affect_correlation` use it and count skipped records
- [ ] 2.6 Count readers: sequence's interaction test, the utterance-outcome reply test and the self-model's voice observation read `text_chars` and `text_words`
- [ ] 2.7 Tests for each consumer's join and missing-entry behaviour; move the existing tests that read `text` off a published transcription or utterance to the companion reader

## 3. Canary and checks (PR 3)

- [ ] 3.1 `tests/test_spoken_text_canary.py` on the fakeredis helpers named in the brief: fake speech-to-text with planted heard sentences on an operator and a media channel, fake organ with planted own sentences, file-backed episodic store, fake vocal backend, the bridge's transcript loop, the three observers; assertions of the spec; planted controls (split disabled; a heard sentence in an intent's `about`)
- [ ] 3.2 Publisher review in the same harness: every string leaf longer than 40 characters on a main-bus stream sits under a reviewed key
- [ ] 3.3 Entity-free score check: every candidate's novelty and salience scores identical with the split on and off
- [ ] 3.4 The canary runs in the default CI lane

## 4. Docs and records

- [ ] 4.1 Security and privacy chapter: the bus holds no words; the stores that keep words on purpose (intent log, episodic store, the local external-utterance record) and their protections; old AOF files hold earlier runs' words until cleared
- [ ] 4.2 Bus chapter: the spoken-text field set beside the latent one on the volatile instance
- [ ] 4.3 `docs/09-modules/language.md`, `audition.md`, `episodic-memory.md`, `sequence.md`, `self-model.md`, `vocal.md`, the remote-bridge page: where each reads its words or counts
- [ ] 4.4 Research-data chapter: the raw bus archive holds no words
- [ ] 4.5 Paper REVISION-NOTES entry (paper repo, §5.3 privacy paragraph): "Heard speech and the entity's own words never reach a persisted bus: they travel on a second, never-persisted bus instance, joined by entry id, and the persisted copies keep only lengths and word counts."

## 5. Review

- [ ] 5.1 Worker first-pass review of each PR
- [ ] 5.2 Lead developer's adversarial review of each PR
- [ ] 5.3 Independent second review of each PR (privacy and persistence)
