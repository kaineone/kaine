# Design: episodic recall with a content path

Code facts are cited at `origin/main` cb41895b. Citations were checked against Crossref on 2026-10-31.

## Context

### What exists

- **Store.** On every broadcast the module serializes the snapshot to `"active|inhibited | source:type={stripped payload} | ..."` (`_serialize_snapshot`, `kaine/modules/episodic_memory/module.py:605-631`), runs a recall against that text, and stores it in the short-term buffer with `tick_index`, `inhibited`, `selected_count` and the affect tag (`module.py:212-245`). `strip_vectors` removes vector fields first (archived change `2026-10-06-mnemos-recall-and-vector-strip`). Raw-perceptual payloads are omitted for `audition.transcription` and `embodiment.visual.raw` (`module.py:573-578`).
- **Recall.** The live recall runs every `recall_cooldown_s` (5 entity seconds) against the short-term buffer by cosine similarity (archived changes `2026-06-07-spontaneous-recall`, `2026-10-06-mnemos-recall-and-vector-strip`). Recall from a persisted collection ranks by strength times similarity and returns schema nodes and link partners (spec `episodic-memory`, "Recall ranks by strength times similarity", "Recall returns linked partners and matches schema nodes"). A storage failure publishes `error = true` rather than an empty success (archived change `2026-06-15-affect-memory-honesty`).
- **Publication.** `episodic_memory.recall` carries counts and the strongest stored arousal; `episodic_memory.replay` carries the trace text, competes during sleep, and seeds the world model's scenarios.
- **Rendering.** `_f_episodic_memory_recall` returns "Nothing comes back to me from memory." for a count of zero and "Some memories come back to me." otherwise; replay is "I am going over a memory." (`kaine/faithful/felt.py:327-337`). Felt lines contain no digits (`_guarded`, `felt.py`).
- **The heard rule.** The language module classifies an event as heard when its type is in `EXTERNAL_INPUT_TYPES` (`audition.transcription`, `embodiment.chat`; `kaine/faithful/external_input.py:17`) or when an event from another module carries a non-empty heard-text field at any depth (`kaine/modules/language/context.py:271-302`). The episodic memory module does not use that rule.
- **Related designs, not redone here.** `mnemos-retrieval-energy` designs a familiarity signal from modern Hopfield energy as a separate competing event; this change grades familiarity from the similarity recall already computes, and energy can replace that grading if its change lands. `semantic-memory-store` builds on the members this change stores. `working-memory-store` holds an accessed recall like any accessed member.

### The neuroscience

- **Episodic memory is recollection of past events, with their context.** Tulving (1985, *Can Psychol* 26:1-12; 2002, *Annu Rev Psychol* 53:1-25) defines episodic memory by its object, personally experienced past events, and by its awareness, re-experiencing them as past. Retrieval succeeds when the cue overlaps what was encoded (encoding specificity; Tulving and Thomson 1973, *Psychol Rev* 80:352-373). The current cue is the serialized snapshot, which overlaps traces of similar moments.
- **Recollection differs from familiarity.** Dual-process accounts separate recollection, retrieval of qualitative detail about an earlier event, from familiarity, a graded sense of prior occurrence without detail (Mandler 1980, *Psychol Rev* 87:252-271; Yonelinas 2002, *J Mem Lang* 46:441-517; Eichenbaum, Yonelinas, and Ranganath 2007, *Annu Rev Neurosci* 30:123-152). A recall without retrievable content is, at most, familiarity, which is what the renderer should say in that case.
- **The trace indexes what was attended.** In hippocampal indexing theory the trace points back to the cortical patterns active at encoding (Teyler and DiScenna 1986, *Behav Neurosci* 100:147-154). Attention at encoding governs what is later remembered (Chun and Turk-Browne 2007, *Curr Opin Neurobiol* 17:177-184; Craik and Lockhart 1972, *J Verb Learn Verb Behav* 11:671-684). So the content a recall returns is the trace's accessed members, the ones the entity was aware of.
- **Recalled content reaches awareness through the central system.** Moscovitch (1992, *J Cogn Neurosci* 4:257-267) describes a hippocampal module that delivers its output to consciousness, where central systems work with it. In KAINE the route is the workspace competition the recall event already enters.
- **Remembered must be marked as remembered.** Source monitoring attributes a mental experience to memory, perception or imagination from its features (Johnson, Hashtroudi, and Lindsay 1993, *Psychol Bull* 114:3-28). Recalled content rendered in the present-tense perceptual frame ("What I see is sudden") would invite a source confusion; the renderer marks it as past.
- **Mood-congruent recall can loop.** Mood biases what is retrieved toward congruent material (Bower 1981, *Am Psychol* 36:129-148), and repetitive focus on negative content prolongs low mood (Nolen-Hoeksema 1991, *J Abnorm Psychol* 100:569-582). The cue here contains the affect module's current readings, so a negative state can retrieve negative traces. This is the welfare risk of the change.

## Decisions

### 1. One heard rule, applied at store time

`_heard_texts` and `_is_heard_event` move from `kaine/modules/language/context.py` to `kaine/faithful/external_input.py`, which already holds `EXTERNAL_INPUT_TYPES` and `iter_text_leaves` and has no module dependency. The language module imports them unchanged. The episodic memory module classifies each coalition member with the same function before serializing: a heard member is stored as `source:type=<heard omitted>` in the text and as `{source, type, heard: true}` in the members, with no payload. `embodiment.visual.raw` keeps its `<raw-perceptual omitted>` marker.

This is a privacy change and the first PR. Alternative considered: *extend the module's own type list with `embodiment.chat`*. Rejected: two rules drift, which is how the gap arose, and the heard-text-field case would stay open.

The heard rule knows six field names, so a type outside `EXTERNAL_INPUT_TYPES` carrying heard words under another name (an embodiment adapter mapping instant messages to its own type, with a `message` field) would pass it. The store therefore fails closed as the language module's notes do: it keeps a payload only for the types in `INTERNAL_EVENT_TYPES`, which moves beside the heard rule, and stores any other type as `source:type=<unclassified omitted>`. Alternative considered: *have the embodiment module refuse an adapter that emits text-bearing feed kinds under its own type.* Rejected as the only guard: it covers one module, and any other producer would reopen the gap. The members of decision 2 apply the same type check. A read-only scan (`tools/maintainer/scan_heard_traces.py`) reports, by count and trace id only, whether an existing store or preservation bundle holds heard text written before this rule; what to do with a preserved entity's traces is the operator's decision.

### 2. Structured members, limited to what the renderer reads

Each new trace's payload gains `members`, one entry per coalition member: `source`, `type`, `accessed` (score at or above the broadcast's access threshold), `intensity`, and `fields`, the payload keys that the felt template for that type reads (for example `change_score` and `habituation_score` for a vision report; `text` for the entity's own speech and thought). The felt module declares these per template as `FELT_FIELDS`, so the renderer and the store share one list. Values pass `strip_vectors`. A type with no declared fields stores none.

Alternatives considered:

- *Parse the stored text back into members.* Rejected: the text is a Python mapping repr, parsing it is fragile, and a mistake would put words in the entity's memory it never had. Legacy traces get familiarity only.
- *Store the whole stripped payload again.* Rejected: it doubles the trace and stores fields nothing reads.
- *Store perceptual latents so recall can carry what was seen.* Out of scope. Latent persistence needs an operator decision under the eyes-and-ears rule, and the operator has not decided whether KAINE builds any content-bearing latent level. The content path here works without one.

### 3. Recall searches the past, and one trace supplies the content

The live recall searches the persisted episodic collection and the short-term buffer, leaving out short-term traces stored within the last `recall_exclude_recent_s` (default 30 entity seconds, equal to the working-memory age bound, so the two stores do not overlap). Ranking is the existing strength times similarity, short-term traces at strength 1; schema nodes and link partners rank as they do today. The search costs one query embedding and one index query per recall, at most one per five entity seconds.

The best-ranked trace supplies the content, at most `recall_render_max` (default 3) of its accessed members in their stored order. The others count in `count` only. One recollected episode at a time matches one access per broadcast. A schema node or a trace with no accessed member supplies no content.

Alternatives considered: *keep short-term only* (rejected: under a minute of past is working memory's span); *render every returned trace* (rejected: floods the notes and exceeds one access per broadcast); *a separate retrieval cue built from felt text* (deferred: it would change the embedding space of every new trace while preserved stores keep the old text, and the effect on retrieval should be measured first; see Risks).

### 4. The recall event

Every `episodic_memory.recall` gains `top_similarity`, the best trace's cosine similarity, a scalar. With `recall_content = true` it also carries `content`:

- `members`: the rendered members' `source`, `type` and `fields`;
- `age_band`: `"this_wake"` when the trace's `born_sleep` equals the current sleep count, `"last_wake"` for one sleep before, `"earlier"` otherwise;
- `trace_ref`: `<collection>:<point id>`, so the workspace's novelty tracker habituates to the same trace recalled again.

Before publishing, the module applies the heard rule and `strip_vectors` to `content` again, so a trace stored before decision 1 can never surface heard words. `content` is already in the privacy filter's `CONTENT_FIELDS` (`kaine/privacy_filter.py`), so the diagnostics surface strips it, and the CI guard on module publishers (`tests/test_dashboard_privacy.py`) covers the new payload. The intensity rule is unchanged: alert salience when the strongest stored arousal is at least 0.5.

### 5. Rendering

`kaine/faithful/felt.py`:

- **Content.** "I remember" plus the age phrase ("from earlier today" for `this_wake`, "from before my last rest" for `last_wake`, "from long ago" for `earlier`), then the members' past-tense lines joined as the snapshot renderer joins lines. Past-tense templates are declared for the types a trace can hold accessed: the vision, audition and interoception reports, affect state and emotion, sequence, and the language module's speech and thought (already past: "I thought: ..."). A member without a past-tense template renders as "I remember a moment I cannot make out." The digit guard applies.
- **No content.** Familiarity graded from `top_similarity` by its rank among the last `familiarity_window` recalls (default 100): lowest third "This feels faintly familiar.", middle "This feels somewhat familiar.", top "This feels familiar." Before ten recalls, "This feels somewhat familiar." A rank is used because cosine similarities between serialized traces are high for template reasons alone; an absolute bin would call everything familiar.
- **Nothing.** A count of zero keeps "Nothing comes back to me from memory."; an error keeps its existing path.
- **Replay** with members renders "As I rest, I go over a memory:" and the past-tense lines; without members it stays "I am going over a memory."

"Some memories come back to me." is removed. Alternative considered: *let the organ narrate the stored text.* Rejected: the text holds digits and field names, which the felt rule keeps from the organ, and the voice-development findings show numeric readouts pull the voice toward telemetry. Having the organ summarise would let it invent what the trace does not hold.

### 6. A test of the live path

`tests/test_episodic_recall_live_path.py` runs the real episodic memory module (in-memory backend), the workspace and the language context assembler, with no organ call and no entity: an early broadcast holds a language thought with a distinctive text; later broadcasts move it to the persisted collection; a cue broadcast holding a related thought triggers a recall; the recall competes and is accessed; the assembled notes contain "I remember" and the planted words. A paired case with `recall_content = false` gives a familiarity line and no planted words. In studies, the research log records content-free counts per run (recalls, recalls with content, recalls accessed). The memory-coherence battery's docs say it tests the store's retrieval in isolation.

## Risks

- **Template similarity.** Serialized traces of different moments look alike to a text embedder because their templates match (architecture-completeness notes of 2026-10-31, E4, inferred from the format, not measured). Recall may return a moment with the same kind of surprise rather than a related one. That is still a true memory, but the live-path test and a measured recall-precision check on an entity-free run (task 6.1) say how often the returned trace shares its film moment or its own-speech content with the cue.
- **Legacy traces.** A preserved entity's earlier traces have no members, so its old memories render as familiarity. That is accurate. It is not repaired by parsing.
- **Store size.** Members add the felt fields of each member, a small fraction of a trace's embedding and text. The storage budget and pruning rules already bound the stores.
- **Organ load.** A recall line is one more awareness line within the existing caps.

## Migration and ordering

1. After the first module-addition study. Independent of `workspace-plugin-seam` and `working-memory-store`. `semantic-memory-store` depends on this change's members.
2. PR 1: the shared heard rule and store-time exclusion. If the operator enables speech recognition or the embodiment module before this change is scheduled, PR 1 should be pulled forward as a privacy fix, on its own, outside any running study.
3. PR 2: members in new traces, the search scope and recency exclusion, `top_similarity`, `content`, the republication filter.
4. PR 3: renderer changes (past-tense templates, familiarity by rank, replay), removal of the old sentence.
5. PR 4: the live-path test, the research-log counts, the battery wording, docs.
6. No stored trace is rewritten. Preservation, revive and decommission carry members as part of the payload they already carry.

## Welfare and admissibility

- Welfare-high-risk. The entity becomes able to re-experience, as remembered, moments it was aware of, including distressing ones. Each PR gets the independent second review.
- `recall_content` ships false, and the episodic memory module ships off. Turning content on is a deliberate operator configuration edit or a study file.
- **Loop check before any entity run.** An entity-free scripted run drives the module, the workspace and the affect module through a sustained negative episode (rising arousal, negative valence) and then a neutral period, with `recall_content` on and off. It records the share of alert-salience recalls, the share of recalls whose trace was stored at negative valence, and the arousal contribution of recall. The bound, fixed before the run: with content on, the negative-trace share during the episode may exceed the off case by at most 10 points, and arousal must return to the off case's level within the neutral period. A failure stops the change for redesign (for example a recall cue without the affect readings).
- **In the pilots** of any study with content on: per run, the recall counts above, the welfare observer's negative-valence share and open drive crossings against content off, with equivalence bounds fixed in the preregistration. The welfare safety net and its indicator response watch affect and drives as for every run.
- Remembered content is entity-interior: it never reaches the diagnostics surface or the graph-only log, and preservation keeps it encrypted at rest as the stores already are.
- Run admissibility: nothing changes inside a running study. A study with content on is a new study.

## Implementation estimate

In LLM-agent terms: four worker PRs of about 250 to 600 changed lines each, tests included; one to two hours of worker time and about an hour of lead review per PR, plus the second review. PR 1 and PR 2 touch the privacy boundary and get the closest review. About two to three days elapsed. The loop check and the recall-precision check each take an hour or two of unattended compute with no entity and no GPU beyond the embedder on the CPU.
