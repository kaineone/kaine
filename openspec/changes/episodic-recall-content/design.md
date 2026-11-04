# Design: episodic recall with a content path

Code facts are cited at `origin/main` cb41895b. Citations were checked against Crossref on 2026-10-31.

## Context

### What exists

- **Store.** On every broadcast the module serializes the snapshot to `"active|inhibited | source:type={stripped payload} | ..."` (`_serialize_snapshot`, `kaine/modules/episodic_memory/module.py:605-631`), runs a recall against that text, and stores it in the short-term buffer with `tick_index`, `inhibited`, `selected_count` and the affect tag (`module.py:212-245`). `strip_vectors` removes vector fields first (archived change `2026-10-06-mnemos-recall-and-vector-strip`). Raw-perceptual payloads are omitted for `audition.transcription` and `embodiment.visual.raw` (`module.py:573-578`).
- **Recall.** The live recall runs every `recall_cooldown_s` (5 entity seconds) against the short-term buffer by cosine similarity (archived changes `2026-06-07-spontaneous-recall`, `2026-10-06-mnemos-recall-and-vector-strip`). Recall from a persisted collection ranks by strength times similarity and returns schema nodes and link partners (spec `episodic-memory`, "Recall ranks by strength times similarity", "Recall returns linked partners and matches schema nodes"). A storage failure publishes `error = true` rather than an empty success (archived change `2026-06-15-affect-memory-honesty`).
- **Publication.** `episodic_memory.recall` carries counts and the strongest stored arousal; `episodic_memory.replay` carries the trace text, competes during sleep, and seeds the world model's scenarios.
- **Rendering.** `_f_episodic_memory_recall` returns "Nothing comes back to me from memory." for a count of zero and "Some memories come back to me." otherwise; replay is "I am going over a memory." (`kaine/faithful/felt.py:327-337`). Felt lines contain no digits (`_guarded`, `felt.py`).
- **The heard rule.** The language module classifies an event as heard when its type is in `EXTERNAL_INPUT_TYPES` (`audition.transcription`, `embodiment.chat`; `kaine/faithful/external_input.py:17`) or when an event from another module carries a non-empty heard-text field at any depth (`kaine/modules/language/context.py:271-302`). The episodic memory module does not use that rule.
- **Related designs, not redone here.** `episodic-memory-retrieval-energy` designs a familiarity signal from modern Hopfield energy as a separate competing event; this change grades familiarity from the similarity recall already computes, and energy can replace that grading if its change lands. `semantic-memory-store` builds on the members this change stores. `working-memory-store` holds an accessed recall like any accessed member.

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

### 1a. Own-content audit: the fields the store keeps beyond `INTERNAL_EVENT_TYPES`

Failing closed on every undeclared pair over-redacts: planning, self-model drift, social cognition, world model, recall, vocal, effector and regulation members lose their whole payload, so the entity's memory of its own state has holes. Widening `INTERNAL_EVENT_TYPES` is not an option, because the set is part of the language module's prompt layout (`layout_digest()`, `76f99c859fe8b7bb`) and also lifts the organ's heard-speech guard. The store therefore has its own declaration, `kaine/faithful/episodic_own_content.py`: `EPISODIC_OWN_CONTENT` is `INTERNAL_EVENT_TYPES` plus the pairs audited below, and each audited pair has a field allowlist. A declared pair keeps only its allowlisted fields whose values pass their rules; every other field, including one a producer adds later, is dropped. No rule admits free text: a string must be one of a fixed set of values, a trace id, or a token of at most 64 characters from `[A-Za-z0-9_.:-]`. The heard rule still runs first. The language module does not read this module, and a test pins the digest.

Classes: **SAFE** (computed by the entity's own modules from internal state, fixed phrases, numbers, code or operator-config labels); **HEARD-DERIVED** (text that can carry words from outside: chat, transcripts, screen or file text, exception messages that can quote what was being processed); **RAW-SENSORY**; **LATENT-DERIVED** (per-dimension values computed from encoder outputs, `latent-content-privacy`). No field below is latent-derived: the world model's `step_magnitudes` and `trajectory_drift`, and every prediction error, are scalar reductions over all dimensions, which that change's definition excludes.

Audited pairs (producer code at `build/heard-rule-shared` 09e2c6e6):

| Pair (producer) | Field | Where the value comes from | Class | Stored |
|---|---|---|---|---|
| `affect.regulation` (`affect/module.py`, regulation tiers) | `tier`, `bias`, `decay_s`, `intensity`, `episode_s`, `size` | tier index, config, arousal/valence computation | SAFE | yes (number) |
| | `action` | fixed phrase per tier | SAFE | yes (fixed set) |
| | `source` | `ThreeTierRegulation.target_source`: the coalition member source with the most negative-intensity mass | SAFE | yes (module names) |
| | `emotion_before`, `emotion_after` | `CategoricalEmotion` values | SAFE | yes (fixed set) |
| `effectors.action` (`effectors/module.py` `_record`, `_record_provenance_rejected`) | `effector` | the act intent's `effector`; on the blocked and provenance-rejected paths any string a forged intent carries | SAFE only as a registered name | only `notify`, `file_write`, `shell` |
| | `success`, `blocked`, `provenance_rejected`, `alert`, `elapsed_ms` | flags, timing | SAFE | yes |
| | `error` | `f"{type(exc).__name__}: {exc}"`: shell stderr, `notify-send` stderr, the requested command, file errors | HEARD-DERIVED | no |
| `embodiment.efference` (`embodiment/module.py` `_drive_control`) | `channels` | the entity's emitted setpoints, keys from `CONTINUOUS_CHANNEL_RANGE`, clamped floats | SAFE | yes (fixed keys, numbers) |
| | `forwarded` | flag | SAFE | yes |
| `episodic_memory.recall` (`episodic_memory/module.py` `recall`) | `count`, `max_affect_intensity`, `error` | recall result | SAFE | yes |
| | `query_length` | length of the cue; for the evaluation battery's query client (`kaine/cycle/__main__.py`) the length of a question someone else wrote, a number only | SAFE | yes |
| | `collection` | caller's argument; the error path echoes an unknown one | SAFE as a collection kind | only `EPISODIC_MEMORY_COLLECTION_KINDS` |
| | `error_detail` | `str(exc)` from the storage or embedder, which can quote the cue | HEARD-DERIVED | no |
| `interoception.warmup.started`, `.completed` | `min_samples`, `min_seconds`, `samples_seen`, `lived_seconds` | config and counters | SAFE | yes |
| `interoception.regulation.withheld` | `would_be_action`, `severity` | `regulation._ACTIONS`, `_SEVERITIES` | SAFE | yes |
| | `prediction_error`, `sustain_elapsed_s` | forward-model L2 error over host telemetry, timer | SAFE | yes |
| | `reason` | fixed `"warmup"` | SAFE | yes |
| `perceptual_locus.changed` | `locus`, `by` | validated against `LOCI`; fixed `"entity"` | SAFE | yes (fixed set) |
| `perceptual_locus.denied` | `requested` | `str()` of the switch intent's `locus`, unvalidated on the denial path | SAFE only as a locus | only `LOCI` |
| | `reason` | fixed phrases from `evaluate_locus_switch` | SAFE | yes (fixed set) |
| `planning.belief` (`planning/module.py`) | `statement` | generative-model state labels (code constants) or `factorN_stateM`; a plugin engine could supply others | SAFE as a known label | only the constants and the positional form |
| | `kind`, `frequency`, `confidence` | fixed `"belief"`; posterior over symbolic states | SAFE | yes |
| `planning.policy` | `policy` | engine action (`ACTION_SPACE`) | SAFE | only `ACTION_SPACE` |
| | `expected_free_energy`, `horizon`, `param_info_gain` | engine numbers and flag | SAFE | yes |
| `planning.proposal` | `proposal_id`, `action`, `kind`, `step`, `preference` | `uuid4().hex`, `ACTION_SPACE`, `_ACTION_TO_PROPOSAL_KIND`, counters | SAFE | yes (id pattern, fixed sets, numbers) |
| `planning.error` | `error_reason` | `f"{type(exc).__name__}: {exc}"` from `engine.step(snapshot)`; the snapshot holds heard members, and an exception message can quote a payload value | HEARD-DERIVED | no |
| | `elapsed_ms`, `num_factors`, `num_actions` | numbers | SAFE | yes |
| `planning.timeout` | `elapsed_ms`, `num_factors`, `num_actions` | numbers | SAFE | yes |
| `self_model.drift` (`self_model/module.py` `on_workspace`) | `score`, `recent_count`, `historical_count`, `reference_count`, `alert` | drift over coalition source names | SAFE | yes |
| | `top_drifted_sources` | coalition source names | SAFE | yes (module names, bounded list) |
| `sleep.association` (`sleep/phases.py`, `memory.py` co-replay) | `a`, `b`, `weight` | the store's own trace keys; link weight | SAFE | yes (id pattern, number) |
| `sleep.ignition_audit` (`sleep/ignition_audit.py` `as_payload`) | `sleep_index` and the nine counts | counts | SAFE | yes |
| | `*_entry_ids`, `event_types`, `saliences` | bus entry ids, member type names, numbers | SAFE | no (unbounded bookkeeping, no experience) |
| | `audit_error` | exception type name | SAFE | no (no experience) |
| `social_cognition.agent_model`, `.social_error` (`social_cognition/module.py`) | `agent_id`, `agent_label` | `[social_cognition].speaker_label` (operator configuration, default `operator`) or `media:<channel>`; only those two forms are admitted. The configured label is persisted as written in every trace that holds a social cognition member and so travels with preservation bundles; it is meant to be a role label, not a person's name (the config comment says so), which is why it is kept while `vocal.synthesized` `voice`, a private voice or clip path, is dropped | SAFE (config) | yes (configured label or `media:` plus a channel) |
| | `source_label` | audition channel name, from code only (`live_mic`, `seeded`, `playlist`, `stimulus_source`, `screen`, `remote`, `microphone`) | SAFE | yes (fixed set) |
| | `familiarity`, `reliability`, `interaction_count`, `salience`, `deviation_magnitude` | scalars from emotion-category histograms; transcripts only bump a count | SAFE | yes |
| `vocal.synthesized` (`vocal/module.py` `_publish_event`) | `text_length`, `bytes_produced`, `latency_ms`, `success` | lengths, timing, flag | SAFE | yes |
| | `exaggeration`, `cfg_weight`, `temperature`, `speed_factor` | prosody from the affect state | SAFE | yes |
| | `backend`, `prosody_applied`, `origin` | config (`chatterbox`, `sherpa_onnx`), code constants, intent origin (`planning`) | SAFE | yes (fixed sets) |
| | `voice` | operator voice label or id (can name a private voice or a clip path) | SAFE source, personal | no |
| | `output_format` | config | SAFE | no (no experience) |
| | `error` | `f"{type(exc).__name__}: {exc}"` from synthesising the entity's speech, which can quote heard words | HEARD-DERIVED | no |
| `world_model.world_error` | `world_error`, `salience`, `tick_index`, `backend`, `engine` | scalar error, config | SAFE | yes (numbers, fixed sets) |
| `world_model.scenario` (`world_model/module.py` `generate_scenario`) | `seed_memory_id` | the replay cue's `memory_id` | SAFE | yes (id pattern) |
| | `horizon`, `step_magnitudes`, `trajectory_drift`, `encoder_version`, `backend`, `engine` | rollout length, per-step mean magnitude, scalar drift, constant, config | SAFE | yes |

Pairs that reach the workspace and stay undeclared:

| Pair | Why |
|---|---|
| `audition.transcription`, `embodiment.chat` | heard by type (`<heard omitted>`) |
| `embodiment.visual.raw` | RAW-SENSORY (`<raw-perceptual omitted>`) |
| any other `embodiment.*` feed kind | the adapter's frame payload: world-side names and metadata the adapter defines, HEARD-DERIVED or RAW-SENSORY (`<unclassified omitted>`) |
| `episodic_memory.replay` | legacy trace text; recorded by id only |
| `self_model.document` | `name` (launch or chosen name), `values`, `behavioral_norms`, `situation_facts` (operator-written persona and boot facts: someone else's written text), `personality_baseline`, `capability_map`; HEARD-DERIVED as file content (`<unclassified omitted>`) |
| `recorder.ping` | test-only module |

Sources outside the module registry (supervisor, lifecycle, housekeeping, individuation, development, preservation monitor, positive control, perception feed) publish to streams the cycle does not read for the workspace, so they cannot be coalition members.

The agent id and label fields are the one place the rule rests on provenance: they admit `media:<channel>` for a fixed channel or a token-shaped label, which is the configured `speaker_label`. A structural test pins that the social cognition module creates agent ids only from `speaker_label` or `media:<source_label>`, so a change that takes labels from heard speech (speaker diarization, for example) fails it, and a test pins that these are the only token fields. Field shape is checked again by the heard-trace scan: a member of an audited pair is clean only when every field is allowlisted and passes its rule, so a legacy trace that kept `error_reason` or `error_detail` text is still flagged.

**Declared types: the playlist media file name.** `vision.report` and `audition.perception`, both in `INTERNAL_EVENT_TYPES`, carry `item`, the basename of the playlist media file (an operator-chosen file name, often a film title). The entity perceives the film, not its file name (the eyes-and-ears rule). The store drops every field in `MEDIA_METADATA_FIELDS` (`kaine/faithful/media_metadata.py`, `{"item"}`, shared with the renderers) from every declared type at any depth, through `declared_payload` and `declared_fields_dropped`; `item_order`, the manifest position, stays. `EPISODIC_DECLARED_FIELD_DENYLISTS` adds the store's own per-pair drops, today only `faithful_rendering` on `internal_speech` and `external_speech`: the rendering repeats the coalition the trace already holds as members, and with the numeric awareness rendering of runs before this change it held the fallback rendering of `audition.perception`, `item` included. Neither list changes `INTERNAL_EVENT_TYPES` or the prompt layout. The renderers strip the same media list (next paragraph). The heard-trace scan flags a legacy trace that kept `item`, or an own-speech `faithful_rendering` holding a rendered `item=`, as `media_item`; with `--intent-log` it counts intent-log records holding a rendered `item=` by record id.

**Where `item` reached the organ and its logs, and the fix (task 3.12, operator decision of 2026-10-31).** Checked by assembling the context for a coalition holding each type with `item` set, before the fix:

| Rendering | `vision.report` | `audition.perception` |
|---|---|---|
| felt (shipped, `config/kaine.toml` `awareness_rendering = "felt"`): organ prompt, `working_memory`, the published and logged `faithful_rendering`, the logged `prompt` | no (`_f_vision_report`, `kaine/faithful/felt.py`) | no (`_f_audition_perception`, `felt.py`) |
| felt: the intent log's `numeric_rendering` (`_numeric_log_line` in `kaine/modules/language/context.py`, `FaithfulRenderer`) | no (`_t_vision_report`, `kaine/faithful/templates.py`, reads no `item`) | yes: no entry in `TEMPLATES`, `redact_heard_speech` returned `None`, and `fallback_template` wrote every field, `item=<basename>` included |
| numeric (the `Language` and `ContextAssembler` default when the config omits the key): organ prompt, logged prompt, `working_memory`, `faithful_rendering` | no | yes, by the same fallback, so the organ read the file name, `language.out` and the `*_speech` streams held it, and the voice-alignment trainer (`kaine/modules/sleep/voice_alignment.py`) read it from the logged `prompt` and `faithful_rendering` |

The operator ruled that the file name never reaches the organ's prompt, the intent log or the voice-alignment pairs, in either mode. One list, `MEDIA_METADATA_FIELDS` in `kaine/faithful/media_metadata.py` (`item`; any payload key a module fills from a playlist position's `title`, which a test checks across `kaine/modules`), serves every surface:

- `FaithfulRenderer.render_event` and `redact_heard_speech` remove it at any depth before any template or fallback runs, in both the numeric and the felt template sets;
- `fallback_template` fails closed on it too, so a future type without a template cannot write it;
- `audition.perception` has a numeric template in the `vision.report` style: *"Audition via {encoder_model_id} reports change {change_score}, prediction error {prediction_error}."* Like the vision template it renders no position, so `item_order` is not rendered;
- the episodic store drops it from every declared type (`declared_payload`).

What the organ and the log see differently: in numeric mode the organ's line for `audition.perception` changes from the fallback, *"audition emitted audition.perception carrying alert=…, attended_seconds=…, …, item=<basename>, item_order=…, …"* (every field in key order), to the template line above; in felt mode the organ's prompt is unchanged and only the intent log's `numeric_rendering` changes the same way. `layout_digest()` is unchanged, because it covers the layout constants and `INTERNAL_EVENT_TYPES`, not the templates. The sleep corpus (`kaine/modules/sleep/corpus.py`) reads only `record_id` and `intent_entry_id`. The cycle broadcast on `workspace.broadcast` still carries each member's full payload, `item` included, until the stream is trimmed (second review, finding C); the bus is the operator's surface for which item is playing.

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

- **Template similarity.** Serialized traces of different moments look alike to a text embedder because their templates match (architecture-completeness notes of 2026-10-31, E4, inferred from the format, not measured). Recall may return a moment with the same kind of surprise rather than a related one. That is still a true memory, but the live-path test and a measured recall-precision check on an entity-free run (task 6.1) say how often the returned trace shares its film moment (by `item_order`, since traces hold no media file name) or its own-speech content with the cue. A comparison with numeric-mode runs before this change also has to allow for the `audition.perception` line, which now renders only change and prediction error where the fallback wrote every field.
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
