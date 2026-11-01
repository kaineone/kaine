## 1. Design (this change)

- [x] 1.1 Record the shared heard rule, the stored members, the search scope, the recall event, the rendering, the live-path test, the loop check and the estimate.

## 2. Start condition

- [ ] 2.1 **Deferred:** the first module-addition study has finished. PR 1 alone is pulled forward, outside any running study, if speech recognition or the embodiment module is enabled first.

## 3. One heard rule (PR 1)

- [x] 3.1 Move `_heard_texts` and `_is_heard_event` to `kaine/faithful/external_input.py` (as `heard_texts` and `is_heard_event`, beside `HEARD_TEXT_FIELDS`); the language module imports them with no behaviour change
- [x] 3.2 The episodic memory module stores heard members as `<heard omitted>` in the trace text (the `heard: true` member entry is part of 4.1, since traces have no members before PR 2)
- [x] 3.3 Tests: `tests/test_external_input_heard_rule.py` (language module's results unchanged on its existing cases); `tests/test_episodic_memory_heard_not_stored.py` (`embodiment.chat`, `audition.transcription`, a nested heard-text field)
- [x] 3.5 Fail closed (second review S2): the trace text keeps a payload only for `INTERNAL_EVENT_TYPES` (moved to `kaine/faithful/external_input.py`); any other type is stored as `<unclassified omitted>`; tests include `embodiment.im={'message': ...}`
- [x] 3.6 Read-only scan of existing stores and bundles (second review S1): `tools/maintainer/scan_heard_traces.py` reports counts and trace ids, never text, and changes nothing; `tests/test_scan_heard_traces.py`
- [x] 3.7 Docs state the remaining limit: the entity's own speech is stored as spoken, including heard words it repeats
- [x] 3.9 Own-content audit (design 1a): `kaine/faithful/episodic_own_content.py` declares 22 audited pairs with field allowlists; the serializer keeps only allowlisted fields that pass their rules; `INTERNAL_EVENT_TYPES` and the layout digest unchanged
- [x] 3.10 Tests: `tests/test_episodic_memory_own_content.py` (safe fields stored, a planted heard string in every field and in unknown fields dropped, heard rule first, value sets match the producers, layout digest); an end-to-end case on a sqlite-vec store in `tests/test_episodic_memory_heard_not_stored.py`; the scan flags an audited pair only outside its allowlist (`tests/test_scan_heard_traces.py`)
- [x] 3.11 The playlist media file name never enters a trace: `EPISODIC_DECLARED_FIELD_DENYLISTS` drops `item` from `vision.report` and `audition.perception` and `faithful_rendering` from the entity's own speech; the scan flags legacy `item` as `media_item`; layout digest unchanged
- [ ] 3.12 **Open, needs the operator's decision (changes what the organ sees):** `audition.perception` has no numeric template, so `fallback_template` (`kaine/faithful/templates.py`) renders its `item` into the intent log's `numeric_rendering` (felt mode, `_numeric_log_line` in `kaine/modules/language/context.py`) and, in numeric mode, into the organ prompt, the published `faithful_rendering` and the voice-alignment training pairs (design 1a)
- [ ] 3.8 Run the scan on the operator's stores and preservation bundles and report the result to the operator before speech recognition or the embodiment module is enabled; rewriting a preserved entity is the operator's decision
- [ ] 3.4 Worker first-pass review, lead review, independent second review (privacy boundary)

## 4. Members, search and the recall event (PR 2)

- [ ] 4.1 `FELT_FIELDS` per felt template in `kaine/faithful/felt.py`; `members` on new traces, a heard member as `{source, type, heard: true}` with no payload (classified with `is_heard_event`)
- [ ] 4.2 Live recall over the persisted collection and the short-term buffer with `recall_exclude_recent_s`
- [ ] 4.3 `top_similarity` on every recall; `content` behind `recall_content`; republication filter
- [ ] 4.4 Config keys `recall_content = false`, `recall_exclude_recent_s = 30.0`, `recall_render_max = 3`, `familiarity_window = 100`
- [ ] 4.5 Tests: `tests/test_episodic_memory_members.py` (felt fields only, no vectors, legacy traces untouched); `tests/test_episodic_memory_recall_scope.py` (earlier wake recalled, recent excluded, schema node yields no content); `tests/test_episodic_memory_recall_content.py` (content shape, age bands, republication filter on a legacy trace holding heard text); `tests/test_dashboard_privacy.py` passes with the new payload
- [ ] 4.6 Worker first-pass review, lead review, independent second review

## 5. Rendering (PR 3)

- [ ] 5.1 Past-tense templates for vision, audition, interoception, affect state and emotion, sequence; the unknown-type line
- [ ] 5.2 Familiarity by rank; the zero-count line; removal of "Some memories come back to me."
- [ ] 5.3 Replay rendering with members
- [ ] 5.4 Tests: `tests/test_felt_recall_content.py`; `tests/test_felt_recall_familiarity.py`; `tests/test_felt_no_content_claim.py` (no output equals the old sentence; "I remember" only with content); digit guard over every new template

## 6. Live path, records and docs (PR 4)

- [ ] 6.1 `tests/test_episodic_recall_live_path.py` (planted thought comes back with content on, not with it off)
- [ ] 6.2 Research-log counts per run: recalls, recalls with content, recalls accessed (content-free)
- [ ] 6.3 Docs: episodic memory chapter (outputs, recall, members), faithful renderer chapter, the memory-coherence battery described as testing the store's retrieval in isolation, configuration appendix; paper notes for §4, §6.4, A.10, Table A1 and §9 in the paper's revision notes
- [ ] 6.4 Worker first-pass review, lead review, independent second review

## 7. Before any entity run with recall content on

- [ ] 7.1 Entity-free loop check (sustained negative episode then neutral period, content on and off) against the bound in the design, recorded under `docs/records/`
- [ ] 7.2 Entity-free recall-precision check on one study film's broadcast sequence: share of recalled traces sharing the cue's film item or own-speech content, recorded under `docs/records/`
- [ ] 7.3 Equivalence bounds for negative-valence share and open drive crossings written into the study's preregistration before its pilots
