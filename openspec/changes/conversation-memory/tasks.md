Design only. Nothing below is built until the ordering in `design.md` holds and the change has been re-reviewed. Every PR is welfare-high-risk and gets the independent second review.

## 1. Guard, speaker rule, switch (PR 1)

- [ ] 1.1 `kaine/faithful/heard_overlap.py`:
  - the ring over words fields only;
  - normalisation: NFKC, case-folding, punctuation and symbols to spaces, digit splitting with number words, character tokens for no-space scripts;
  - matching against the concatenation of the whole ring, in heard order;
  - masking above `max_shared_run`;
  - withholding for gists and accounts only;
  - `(a number)` for runs of three or more digits in gists, accounts and `said`, and masking of shared runs of three or more digits in other own speech;
  - counts.

  Unit tests: hyphenation, a card number with and without spaces, a run across three utterances, a repeated PIN in `said`, a Chinese sentence, a translation, an email address and a homoglyph copy (both reported as unbounded), runs at the bound, an echo reply kept.
- [ ] 1.2 `speaker_for(event, operator_sources, speaker_label)` in `kaine/faithful/external_input.py`. Operator label only for listed channels; `media:`, `world:chat`, `unknown` otherwise. Social cognition is unchanged. A test pins every case.
- [ ] 1.3 Code defaults for `[conversation_memory]`, with no section in the shipped `config/kaine.toml`. Rows in the configuration appendix, each engineering value labelled.
- [ ] 1.4 `layout_digest(conversation_memory: bool = False)`, with every caller, `probe_conditions` among them, passing the setting.
- [ ] 1.5 Golden-file off-switch test. Capture golden outputs of one scripted entity-free sequence from the pre-change build (after the dependencies merge) and compare the new build with the setting absent and false, config digest included.

## 2. Encrypted conversation store (PR 2)

- [ ] 2.1 `EPISODIC_MEMORY_CONVERSATION_KIND` in `kaine/memory_kinds.py`.
- [ ] 2.2 `kaine/modules/episodic_memory/conversation_store.py` (re-prune at the floor and compact at initialize, after a crash between pruning and compaction):
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
- [ ] 2.5 Preservation carries the store. Revive exits 7 when the bundle holds a store and the setting or encryption is off. Fork copies the store to the fork's prefix path. A merge writes the union of both parents' records, with B's `log_base` rebased by `L_b - L_a`, new ids on collision, `merged_from` on each record, and an exact recompute of the total. Decommission backs up and removes every prefix's store. `tools/maintainer/scan_heard_traces.py` reads the store (counts and ids only).
- [ ] 2.6 Associative replay excludes conversation traces as candidates, partners and schema members.

## 3. Bus (PR 3)

- [ ] 3.1 Add `CONVERSATION_TEXT_FIELDS = {"gist", "account", "said"}` to `split_spoken_text`, with `SPOKEN_TEXT_RULE_VERSION = 2`.
- [ ] 3.2 Confirm that the language module's `language.out` producer declaration covers the `comprehension` event's `text`, and test it.
- [ ] 3.3 While the setting is on, an exact periodic sweep (`XTRIM <stream> MINID = <now - companion_max_age_s>` every `companion_sweep_s`, and on every write) over the companion streams of the external-input producers, `workspace.broadcast`, `episodic_memory.out`, `language.out`, `language.external` and `language.internal`. Coordinate with the volatile-bus builder: this exact sweep is the contract for its generic age-bound support. Tests: an entry left with no later write is gone within `companion_max_age_s + companion_sweep_s`; the trim is exact; consumers follow the missing-entry rule.
- [ ] 3.4 Add to the volatile-bus canary a conversation recall with content and a `comprehension` event on `language.out`, covering the `language.out` companion.

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
- [ ] 4.3 `comprehension` events on `language.out`, at the accessing heard event's intensity, competing for access. They are never published on `language.external` or `language.internal`. `("language", "comprehension")` is a declared internal type under the setting. Tests: a gist can win access; the self-model, the utterance-outcome recorder, the vocal module and the report policy ignore it; the raw archive keeps only the content-free copy.
- [ ] 4.4 The episode request, from accessed gists and the entity's own words only.
- [ ] 4.5 The held-utterance attribution in the user turn, with the placeholder in the logged heard turn.
- [ ] 4.6 The heard-speech guard ends the persona whenever a comprehension member, an episode-notes line or recalled conversation content is in the prompt.
- [ ] 4.7 Intent-log records with `mode = "comprehension"`, holding no text. `[remembered conversation]` replaces every comprehension, episode-notes and recalled-conversation line in the logged prompt, `faithful_rendering`, the numeric rendering and `about_values`. The voice-alignment builder (`kaine/modules/sleep/voice_alignment.py:262-283`), every other pair builder and `tools/maintainer/organ_replay.py` skip that mode, and any record holding the placeholder in any rendering, before counting, and count the skips as `voice_records_skipped_conversation`.
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
  - the planted text across three utterances, with hyphenated, 16-digit and no-space variants;
  - a copying stub organ;
  - accessed gists rendered into the notes, so a renderer-level leak would show;
  - two sleeps with association on, a recall, preservation, a fork, a merge, a decommission backup;
  - scans of the decrypted files, the decrypted intent log with every rendering, main-bus writes and logs;
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
- [ ] 8.6 After the CTO's ruling on open question 2: a maintainer tool for legally required erasure under CAL Article 4.3's carve-out. It deletes the conversation traces of a named speaker label and time span from the live store (and named bundles where the law requires), writes a content-free audit record, and puts a situation fact telling the entity that some memories were removed for a legal reason.
