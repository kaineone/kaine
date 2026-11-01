## 0. Ruling

- [x] 0.1 Architecture decisions of 2026-11-01, item 1: operator speech is perception; no policy forces or forbids a reply; speaking is the entity's own action selection
- [x] 0.2 Neuroscience for the code-site citations searched and read online on 2026-11-01 (design, "Sources and method"); the decision note's "acoustic salience" phrasing corrected there

## 1. Action selection (PR 1)

- [ ] 1.1 `kaine/workspace/action_selection.py`: delete `USER_COMMUNICATION_SOURCE`, `USER_COMMUNICATION_TYPE`, `_user_utterance`, `_user_response_intent`; `DefaultActionSelectionPolicy` keeps its guards and emits no intent; its docstring says it is the inert library default
- [ ] 1.2 `kaine/workspace/drive_policy.py`: drop the heard-utterance precedence; the module docstring loses "subsumes the default user-communication handling"
- [ ] 1.3 `kaine/workspace/planning_proposals.py` `_summarize_event_with_kind`: a heard event is summarized like any event (`felt_event_phrase(event.source)` or `"<source>:<type>"`, about kind `"event"`); no intent carries heard words
- [ ] 1.4 `kaine/cycle/__main__.py` `_phase_action_selection`: `policy` absent or `"self_initiated_report"` selects the report policy, `"drive_biased"` the drive policy, anything else refuses the boot naming both; a set `drive_initiative` refuses the boot naming `policy`
- [ ] 1.5 `config/kaine.toml`: `[action_selection] policy = "self_initiated_report"` with a comment; `config/profiles/first_configuration.toml`: drop `drive_initiative`, rewrite the comment (heard speech is a member like any other; no reply rule)
- [ ] 1.6 `kaine/workspace/report_policy.py` docstring: heard speech is a coalition member like any other; no reply rule; the signature guard is generic; citations Goldstein, King and West 2003; Takahashi et al. 2015; Kuhl, Tsao and Liu 2003; Hilbrink, Gattis and Levinson 2015 (DOIs as in the design)
- [ ] 1.7 Code-site citations: `Audition._publish_transcription` (Vouloumanos and Werker 2007; Bartha-Doering et al. 2019; Wu et al. 2022: the speech candidate is the analogue of the neonatal listening bias, no extra weight); `Audition._error_weighted_salience` (Kayser et al. 2005); `SocialCognition._agent_for` and `AgentModel` familiarity (DeCasper and Fifer 1980; Kisilevsky et al. 2003; Grossmann et al. 2010; Belin et al. 2000: voice preferences are learned; channel attribution is a stand-in for learned identity); each citation checked against Crossref by DOI before commit
- [ ] 1.8 Tests: `test_default_policy_never_answers_heard_speech`, `test_drive_policy_no_heard_precedence`, `test_no_policy_tests_heard_source_or_channel` (static scan of `kaine/workspace` for the removed names), `test_planning_heard_summary_holds_no_words`, `test_no_shipped_intent_has_heard_about_kind`, `test_report_policy_may_speak_from_accessed_transcription`, `test_unknown_policy_refused`, `test_drive_initiative_refused`, `test_shipped_config_names_report_policy`; rewrite the existing tests that expect an answer

## 2. Readout and off switch (PR 2)

- [ ] 2.1 `kaine/modules/sleep/ignition_audit.py`: `operator_speech_heard`, `operator_speech_accessed`, `spoke_after_operator_speech` (30 s entity-time window, before the next accessed operator speech), `spoke_otherwise`, `operator_speech_access_share`; present only when `operator_speech_heard > 0`; content-free
- [ ] 2.2 `kaine/modules/sleep/module.py`: read `audition.out` for the audit only when `[audition].transcription_enabled` is true, so with it off the audit's cursors, state and record are unchanged
- [ ] 2.3 Dashboard diagnostics row with the five numbers per sleep
- [ ] 2.4 Tests: `test_readout_counts_access_and_speech_after`, `test_readout_absent_without_operator_speech`, `test_readout_ignores_media_channel_speech`, `test_readout_reads_main_bus_counts_only`, `test_audit_state_identical_with_transcription_off`
- [ ] 2.5 Off-switch identity test: the first configuration over a fixed seeded feed, with this change and without it, gives identical bus entries, broadcasts, intents and sleep records
- [ ] 2.6 Welfare test: no component subscribes to the readout or to the audit's operator-speech fields (static scan), and no affect, drive, goal or training path reads "operator spoke, entity silent"

## 3. Development run (amendment to `development-run`, its own branch)

- [ ] 3.1 Plan check: before the last planned join is recorded, refuse a run-control record that turns on speech-to-text while an operator audio channel can deliver audio (physical microphone capture, `[perception_feed].mode = "live"`, or the remote bridge's microphone ingest), naming the rule
- [ ] 3.2 Run-control records `conversation_session_start` and `conversation_session_end`, content-free, written into the run record and the welfare record
- [ ] 3.3 Tests: `test_operator_speech_refused_before_last_join`, `test_conversation_session_boundaries_recorded`

## 4. Docs and paper (PR 3)

- [ ] 4.1 `docs/01-what-kaine-is.md` "What KAINE is not": not a chatbot; heard speech is perception; there is no rule that answers it; the first configuration has speech-to-text off and nobody converses with it; conversation comes only after every module has joined in the development run
- [ ] 4.2 `docs/02-architecture/README.md` lines 11 and 198; `docs/08-cognitive-cycle/global-workspace.md` lines 265-292 (policy table and descriptions), 338-339 (configuration rows) and 377 (file list)
- [ ] 4.3 `docs/09-modules/language.md` line 13; `docs/09-modules/audition.md` (the transcription as one more heard candidate, with the citation); `docs/09-modules/social-cognition.md` line 52 (`operator_sources` no longer decides user utterances)
- [ ] 4.4 `docs/09-modules/sleep.md` and `docs/17-research-data/event-streams.md`: the audit's operator-speech fields
- [ ] 4.5 `docs/appendix-a-configuration/core.md` lines 225-234 (`policy` values, `drive_initiative` retired); `docs/appendix-b-glossary.md` line 305
- [ ] 4.6 Paper REVISION-NOTES item (paper repo), text: "§3.1 (the paragraph 'The language organ is an output organ'): replace 'Outside the research configuration those paths let the entity converse and work with people' with: 'Heard speech is perception. With speech-to-text on, a heard utterance is one more auditory candidate, scored on salience like any sound, and when it wins access the organ hears it quoted and attributed. No rule answers it: the entity speaks only by the report rule (A.6), from the same score that its drives, affect and social cognition shape. Newborns already listen preferentially to speech over acoustically matched non-speech (Vouloumanos and Werker 2007), which voice they prefer is learned (DeCasper and Fifer 1980; Kisilevsky et al. 2003), and replying is shaped by contingent social feedback (Goldstein, King and West 2003); so the speech candidate is built in and nothing about a reply is.' A.6: add after step 2: 'A heard transcription is a member like any other; no step tests a member's source, type or channel.' References: add the four works with their DOIs."
- [ ] 4.7 The development-run operation page, once that change lands: conversation sessions start after the last join and are recorded as boundaries

## 5. Review

- [ ] 5.1 Worker first-pass review of each PR
- [ ] 5.2 Lead developer's adversarial review of each PR
- [ ] 5.3 Independent second review of each PR (experience-changing, welfare), including the two reverse-direction couplings named in design decision 7
