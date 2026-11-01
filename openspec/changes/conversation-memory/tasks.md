Design only. Nothing below is built until the ordering in `design.md` holds and the change has been re-reviewed. Every PR is welfare-high-risk and gets the independent second review.

## 1. Guard, speaker rule, switch (PR 1)

- [ ] 1.1 `kaine/faithful/heard_overlap.py`:
  - the ring over words fields only;
  - normalisation: NFKC, case-folding, punctuation and symbols to spaces, digit splitting with number words, character tokens for no-space scripts;
  - matching against each entry and each pair of consecutive entries;
  - masking above `max_shared_run`;
  - withholding for gists and accounts only;
  - `(a number)` for runs of three or more digits;
  - counts.

  Unit tests: hyphenation, a card number with and without spaces, a run across two utterances, a Chinese sentence, a translation (reported as unbounded), runs at the bound, an echo reply kept.
- [ ] 1.2 `speaker_for(event, operator_sources, speaker_label)` in `kaine/faithful/external_input.py`. Operator label only for listed channels; `media:`, `world:chat`, `unknown` otherwise. Social cognition is unchanged. A test pins every case.
- [ ] 1.3 Code defaults for `[conversation_memory]`, with no section in the shipped `config/kaine.toml`. Rows in the configuration appendix, each engineering value labelled.
- [ ] 1.4 `layout_digest(conversation_memory: bool = False)`, with every caller, `probe_conditions` among them, passing the setting.
- [ ] 1.5 Golden-file off-switch test. Capture golden outputs of one scripted entity-free sequence from the pre-change build (after the dependencies merge) and compare the new build with the setting absent and false, config digest included.

## 2. Encrypted conversation store (PR 2)

- [ ] 2.1 `EPISODIC_MEMORY_CONVERSATION_KIND` in `kaine/memory_kinds.py`.
- [ ] 2.2 `kaine/modules/episodic_memory/conversation_store.py`:
  - `state/episodic_memory/conversation/<collection_prefix>/`;
  - an encrypted `snapshot.enc`, written atomically (temporary file, fsync, `os.replace`, directory fsync);
  - an encrypted append-only `journal.enc`;
  - compaction at every sleep after pruning and at shutdown.

  Test: a pruned trace's ciphertext is gone.
- [ ] 2.3 The routing storage over all `MemoryStorage` methods:
  - unions for `wake_points`, `scan_store`, `count_filtered`, `export` and `total_size`;
  - merged order for `weakest`;
  - the meta split: the backend keeps `L` and the sleep count, the conversation store keeps its total, bytes and `applied_sleep`;
  - the write order, and initialize catch-up of missed per-level decrements.

  Tests cover a crash between the two writes.
- [ ] 2.4 Boot refusals: without state encryption, without `require_encryption`, without a non-persisting volatile instance that can trim by age, without both modules, or with `replay_redact_content = false`. Each refusal has a test.
- [ ] 2.5 Preservation carries the store. Revive exits 7 when the bundle holds a store and the setting or encryption is off. Fork copies the store to the fork's prefix path. Merge refuses without an operator choice of parent and records the choice. Decommission backs up and removes every prefix's store. `tools/maintainer/scan_heard_traces.py` reads the store (counts and ids only).
- [ ] 2.6 Associative replay excludes conversation traces as candidates, partners and schema members.

## 3. Bus (PR 3)

- [ ] 3.1 Add `CONVERSATION_TEXT_FIELDS = {"gist", "account", "said"}` to `split_spoken_text`, with `SPOKEN_TEXT_RULE_VERSION = 2`.
- [ ] 3.2 Declare `language.comprehension` as a companion producer, with its capped companion stream.
- [ ] 3.3 While the setting is on, an age bound (`companion_max_age_s`, `XADD ... MINID`) on companion entries carrying heard words or conversation fields. Test: an entry past the bound is missing, and its consumers follow the missing-entry rule.
- [ ] 3.4 Add a conversation recall with content and a comprehension event to the volatile-bus canary.

## 4. Language module (PR 4)

- [ ] 4.1 `kaine/modules/language/conversation.py`:
  - the heard buffer, from words fields only, with its age bound and clears;
  - the episode state and its boundaries;
  - the content-free busy file `state/language/organ_busy.json`.
- [ ] 4.2 The comprehension request:
  - own-turn layout, `gist_max_tokens`, on accessed heard events only;
  - queued behind speak and think;
  - interrupt cancels, re-queues once, then withholds as `"interrupted"`;
  - counts in `is_idle()`;
  - the `gist_truncated` fallback;
  - the failure paths.
- [ ] 4.3 `comprehension` events on `language.comprehension`, competing for access. `("language", "comprehension")` is a declared internal type under the setting.
- [ ] 4.4 The episode request, from accessed gists and the entity's own words only.
- [ ] 4.5 The held-utterance attribution in the user turn, with the placeholder in the logged heard turn.
- [ ] 4.6 The heard-speech guard ends the persona whenever a comprehension member, an episode-notes line or recalled conversation content is in the prompt.
- [ ] 4.7 Intent-log records with `mode = "comprehension"`, holding no text. The voice-alignment builder (`kaine/modules/sleep/voice_alignment.py`), every other pair builder and `tools/maintainer/organ_replay.py` skip that mode, and skip `[remembered conversation]` prompts, before counting.
- [ ] 4.8 Masking on `generated_text` of external and internal records, and in `kaine/evaluation/observers/external_utterance_log.py`.
- [ ] 4.9 The sleep module's organ window waits for the busy file to report idle, or for `episode_close_timeout_s` since sleep onset, before it writes the resting state and unloads.

## 5. Traces and recall (PR 5)

- [ ] 5.1 Utterance and episode traces from accessed and returned comprehensions, with the fields of decision 5. Embed content only. Speaker as metadata.
- [ ] 5.2 Store comprehension members of broadcast traces as references. Mask own-speech members.
- [ ] 5.3 Conversation-cued recall:
  - speaker filter;
  - in-process cue;
  - `trace_recall_cooldown_s`;
  - content through the recall content path.
- [ ] 5.4 Felt templates and speaker phrases, `unknown` included. Episode notes from accessed comprehensions only. `[remembered conversation]` in the logged prompt.
- [ ] 5.5 Per-level downscaling with an exact recompute of the conversation store's total. Tests: pruning within seven sleeps; recall rewrites nothing.
- [ ] 5.6 Replay of conversation traces carries no `text` on the main bus.
- [ ] 5.7 Amend the `episodic-recall-content` implementation to the exception requirement for conversation content.

## 6. Readout, canary, docs (PR 6)

- [ ] 6.1 The `conversation_memory.counts` allowlist, and `tools/maintainer/conversation_memory_readout.py`.
- [ ] 6.2 `tests/test_conversation_memory_canary.py`:
  - the planted text across two utterances, with hyphenated, 16-digit and no-space variants;
  - a copying stub organ;
  - two sleeps with association on, a recall, preservation, a fork, a decommission backup;
  - scans of the decrypted files, main-bus writes and logs;
  - the backend-vector proxy scan;
  - the deletion check;
  - companion ages;
  - buffer and ring after their bounds;
  - controls: guard off, encryption off, revive with the setting off.
- [ ] 6.3 Docs:
  - the privacy statement of design decision 14, word for word, in the security and privacy chapter and the language chapter;
  - the guard's limits;
  - the channel-label limit;
  - the pretrained-model disclosure (decision 8);
  - the `speaker_for` difference from social cognition;
  - swap and core dumps for the in-process cue;
  - preservation, merge and revive behaviour;
  - the configuration appendix.
- [ ] 6.4 Paper revision notes (`predictive-workspace-paper/REVISION-NOTES.md`): §3.5, §4, §9 and Table A1. The paper itself is not edited.

## 7. Before any entity run

- [ ] 7.1 The offline organ measure: at least 200 utterances at two seeds, on a free GPU window. Bounds fixed before the run.
- [ ] 7.2 The downstream injection replay: five imperatives, 40 samples each, of the reply after a gist line, against the direct-reply baseline.
- [ ] 7.3 The topic-selectivity check, entity-free.
- [ ] 7.4 The welfare loop check (decision 12) on the real loop: three seeds, setting on and off, two sleeps, the fixed tolerances. Also `episodic-recall-content`'s own loop check with the setting on.
- [ ] 7.5 Record the results in `docs/records/`. A failure blocks enabling until redesign and a new measurement.

## 8. Follow-ups outside this change

- [ ] 8.1 Event boundaries from prediction error, in place of the silence gap.
- [ ] 8.2 Application-layer encryption of every episodic collection. After it, associative replay could include conversation traces again.
- [ ] 8.3 The overlap guard's masking applied unconditionally to the intent log and the external-utterance log: a privacy fix of the known echo limit, with its own review.
- [ ] 8.4 Words-field-only heard lines on main (review P8): `kaine/faithful/external_input.py:109-110` with `kaine/modules/language/context.py:333-334`.
- [ ] 8.5 Align social cognition's missing-channel mapping with `speaker_for`.
