## 1. Design (this change)

- [x] 1.1 Record the store, its filling, displacement and age rules, the `held` field, the two uses and four arms, the checks before any entity run, and the estimate.

## 2. Start condition

- [ ] 2.1 **Deferred:** the first module-addition study has finished and the pre-study capacity change (one access per broadcast) has merged.

## 3. Store and broadcast field (PR 1)

- [ ] 3.1 `kaine/workspace/working_memory.py`: entries, same-kind replacement, capacity displacement, `max_age_s`, clearing at sleep onset and boot
- [ ] 3.2 `WorkspaceSnapshot.held`, filled after the access decision in all three workspace arms
- [ ] 3.3 Research log: held entry id, source, type and age; no payload
- [ ] 3.4 `[working_memory]` keys in `config/kaine.toml` with `arm = "off"`, and the key guard
- [ ] 3.5 Tests: `tests/test_working_memory_store.py` (filling, replacement, displacement, age, sleep and boot clearing, matched and pooled filling); `tests/test_working_memory_off_bitwise.py`; `tests/test_working_memory_not_persisted.py` (serialize, checkpoint, preservation bundle); `tests/test_ignition_log_held_no_payload.py`

## 4. Context arm (PR 2)

- [ ] 4.1 `BroadcastContext` adopts held entries under `context` and `both`; intensity-weighted mean age; null context over the same entries
- [ ] 4.2 The arm in the workspace-mediation runner, entity-free
- [ ] 4.3 Tests: `tests/test_working_memory_context_capacity_one.py` (equals the current context under one access per broadcast); `tests/test_working_memory_context_null.py`
- [ ] 4.4 Worker first-pass review, lead review, independent second review

## 5. Notes arm and docs (PR 3)

- [ ] 5.1 Awareness block renders held entries after the coalition with recency phrases; caps drop held entries first; heard entries as the placeholder line
- [ ] 5.2 Recency phrases in `kaine/faithful/felt.py`, digit-free
- [ ] 5.3 Tests: `tests/test_language_notes_held.py` (order, phrases, caps, no digits); `tests/test_language_notes_held_heard.py` (no heard words in prompt, logged working memory or numeric log rendering)
- [ ] 5.4 Docs: the short-term buffer in `docs/09-modules/episodic-memory.md` and `docs/06-operation/development.md` is described as the episodic memory module's staging buffer, not working memory; global workspace and language chapters; configuration appendix; paper notes for §3.2, §3.5, A.1, A.8, Table A1 and §9 in the paper's revision notes
- [ ] 5.5 Worker first-pass review, lead review, independent second review

## 6. Before any entity run with an arm on

- [ ] 6.1 Entity-free mediation-runner run on one study film per arm against `off`: information gain, intensity and arousal distributions, recorded under `docs/records/`
- [ ] 6.2 Organ replay of the same moments under `notes` and `off` (length, repetition across consecutive turns, self-description share), outside any entity run, results kept in a private scratch directory and summarised content-free under `docs/records/`
- [ ] 6.3 Equivalence bounds for arousal, negative-valence share, open drive crossings and speak and think rates written into the study's preregistration before its pilots
