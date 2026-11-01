Design only. Nothing below is built until the ordering in `design.md` holds and the CTO has answered open questions 1 to 3. Every PR is welfare-high-risk and gets the independent second review.

## 1. Guard, speaker function, switch (PR 1)

- [ ] 1.1 `kaine/faithful/heard_overlap.py`: the in-process ring (`guard_window_s`), normalisation, maximal shared runs, masking above `max_shared_run`, withholding on `max_heard_coverage` and `min_own_tokens`, and the counts. Unit tests cover runs at the bound, tiling, punctuation and case, an empty ring, and a ring entry that is dropped by age.
- [ ] 1.2 Move the speaker rule out of `SocialCognition._agent_for` (`kaine/modules/social_cognition/module.py:180-190`) into a shared function beside the heard rule. Social cognition calls it unchanged, and a test pins its outputs for the operator, no-channel and `media:` cases.
- [ ] 1.3 Add `[conversation_memory]` keys to `config/kaine.toml` (all off) with the configuration appendix rows, each engineering value labelled as such.
- [ ] 1.4 Test that absent and `enabled = false` are byte-identical over one scripted entity-free sequence. A separate test pins `layout_digest()` unchanged when off.

## 2. Encrypted conversation store (PR 2)

- [ ] 2.1 Add `EPISODIC_MEMORY_CONVERSATION_KIND` to `kaine/memory_kinds.py`.
- [ ] 2.2 `kaine/modules/episodic_memory/conversation_store.py`: an in-memory index whose records (vector, text and payload) are persisted as encrypted JSONL envelopes, with compaction after pruning. Add the routing storage that sends `conversation` to it and every other collection to the configured backend.
- [ ] 2.3 Boot refusal (preboot and cycle) when enabled without state encryption, without `require_encryption`, without a non-persisting volatile instance, or without both modules. Each refusal has a test.
- [ ] 2.4 Preservation export and import, revive, the fork copy, decommission backup and removal (`kaine/lifecycle/decommission.py`), and `tools/maintainer/scan_heard_traces.py` reading the store (counts and ids only).

## 3. Heard buffer and comprehension (PR 3)

- [ ] 3.1 `kaine/modules/language/conversation.py`: the heard buffer (`heard_buffer_utterances`, `heard_buffer_max_age_s`, the clears), the episode state and its boundaries (`episode_gap_s`, sleep onset, freeze, shutdown).
- [ ] 3.2 The comprehension request in the own-turn layout ("## What I took from it", `gist_max_tokens`) on accessed heard events only. The in-flight deferral, the failure paths that record a withheld gist, and publication on the volatile instance only.
- [ ] 3.3 The episode request ("## What that conversation was to me", `episode_max_tokens`, `episode_close_timeout_s`) from the gists and the entity's own words only.
- [ ] 3.4 The held-utterance attribution in the user turn, and the placeholder in the logged heard turn.
- [ ] 3.5 Intent-log records with `mode = "comprehension"` and no generated text. Every pair builder skips the mode.
- [ ] 3.6 The overlap guard on `generated_text` of external and internal records, and on the external-utterance research log. The spoken text is unchanged.
- [ ] 3.7 `layout_digest()` includes the new constants only when enabled.

## 4. Traces, recall, rendering, forgetting (PR 4)

- [ ] 4.1 Utterance and episode trace formation in the episodic memory module from `language.comprehension` (volatile), with the fields of design decision 5. No field holds heard words.
- [ ] 4.2 The overlap guard on own-speech members of broadcast traces (`<withheld: heard overlap>`).
- [ ] 4.3 Conversation-cued recall (speaker label, heard words and gist, embedded in process, never stored) through the recall content path. Content travels on the volatile instance only.
- [ ] 4.4 Felt templates for remembered conversation lines and speaker phrases, with the digit guard. The episode notes ("Earlier in this conversation I took it that ...", `episode_notes_max`). `[remembered conversation]` in the logged prompt.
- [ ] 4.5 Per-level downscaling (`utterance_retention_per_sleep`) after the ordinary downscaling, with replayed traces protected. Tests: pruning within seven sleeps unreplayed; recall changes no strength, content or affect tag.
- [ ] 4.6 Replay of conversation traces carries no `text` on the main bus.

## 5. Readout, canary, docs (PR 5)

- [ ] 5.1 The `conversation_memory.counts` event in the research log allowlist, and `tools/maintainer/conversation_memory_readout.py` in plain words.
- [ ] 5.2 `tests/test_conversation_memory_canary.py`: the planted sentence, the copying stub organ, the full path including sleep, recall, preservation and decommission backup. Scan the decrypted files, main-bus writes and logs for five-token runs. Check the buffer and the ring after their bounds. Include the disabled-guard control and the encryption-off refusal.
- [ ] 5.3 Docs: the language, episodic memory, sleep and social cognition chapters. Add the privacy statement of design decision 12 to the security and privacy chapter and the language chapter. Add the speaker-by-channel limit, and the adult-comprehension disclosure of design decision 8. Update preservation and the configuration appendix.
- [ ] 5.4 Paper revision notes (`predictive-workspace-paper/REVISION-NOTES.md`): §3.5, §4, §9 and Table A1 entries. The paper itself is not edited.

## 6. Before any entity run

- [ ] 6.1 Welfare loop check (design decision 11): an entity-free scripted run with the change on and off, with the bounds fixed in its record before the run.
- [ ] 6.2 Offline organ measure: at least 200 heard utterances at two seeds through the real organ on a free GPU window. Report the longest shared run, trigram overlap, coverage, masked and withheld shares against the fixed bounds.
- [ ] 6.3 Injection replay: the five injected imperatives, 40 samples each, through comprehension. Compare against the reply-path obedience rate.
- [ ] 6.4 Record the three results in `docs/records/`. A failure blocks enabling until redesign.

## 7. Follow-ups outside this change

- [ ] 7.1 Event boundaries from prediction error (the sequence module) in place of the silence gap, as its own change.
- [ ] 7.2 Application-layer encryption of every episodic collection, after which the conversation store could rejoin the backend.
- [ ] 7.3 The overlap guard applied unconditionally to the intent log and the external-utterance log, as a privacy fix of the known echo limit, with its own change and its own off-path review.
