## MODIFIED Requirements

### Requirement: Diagnostics-only bus event for recall
Each `recall` call SHALL publish an `episodic_memory.recall` event to `episodic_memory.out` containing `count`, `collection`, `query_length`, the maximum affect intensity among the returned memories and `top_similarity`. It SHALL NOT include the raw query text or any trace text. With `[episodic_memory].recall_content` false, the shipped value, it SHALL include no memory content. With it true, it SHALL include `content` as specified in "Recall content comes from the best trace's accessed members".

#### Scenario: Recall publishes count without contents
- **WHEN** `recall(query, k=5)` returns 3 matched memories and `recall_content` is false
- **THEN** the published event has `count == 3`, a `top_similarity` value, and no field containing a memory text, a member payload or the query string

#### Scenario: The query text is never published
- **WHEN** `recall_content` is true and a recall returns a trace with content
- **THEN** the published event carries `content` and still holds neither the query string nor any trace text

## ADDED Requirements

### Requirement: Heard events are stored without their words
The episodic memory module SHALL classify each coalition member with the shared heard rule in `kaine/faithful/external_input.py`, the rule the language module uses. A heard member SHALL be stored as `source:type=<heard omitted>` in the trace text and as `{source, type, heard: true}` in the trace's members, with no payload.

#### Scenario: A chat message is not stored
- **WHEN** a broadcast's coalition holds an `embodiment.chat` event whose text is "hello there"
- **THEN** the stored trace's text and members contain no "hello there" and mark that member as heard

#### Scenario: Heard text nested in another module's payload is not stored
- **WHEN** a coalition member from the social cognition module carries a heard-text field at depth two
- **THEN** the stored trace holds that member as heard with no payload

### Requirement: Only declared own-content types keep their payload in a trace
The episodic memory module SHALL keep a member's whole payload in the trace text only when its `(source, type)` is in `INTERNAL_EVENT_TYPES` (`kaine/faithful/external_input.py`) and the member is not heard, and part of it only for an audited pair (next requirement). Any other type SHALL be stored as `source:type=<unclassified omitted>`; `embodiment.visual.raw` keeps `<raw-perceptual omitted>` and this module's replay `<replay of {memory_id}>`.

#### Scenario: An instant message under an adapter's own type is not stored
- **WHEN** a broadcast's coalition holds `embodiment.im` with payload `{"message": "hello there"}`
- **THEN** the stored trace text holds `embodiment:embodiment.im=<unclassified omitted>` and no "hello there"

#### Scenario: A declared report keeps its payload
- **WHEN** a broadcast's coalition holds a `vision.report` with `change_score` 0.25
- **THEN** the stored trace text holds that payload after `strip_vectors`

### Requirement: The playlist media file name is not stored
The episodic memory module SHALL drop, at any depth, `item` from `vision.report` and `audition.perception` members and `faithful_rendering` from `internal_speech` and `external_speech` members, and keep the rest of their payloads. The rule SHALL live in the store's own declaration and change neither `INTERNAL_EVENT_TYPES` nor the language module's rendering.

#### Scenario: A film's file name is not stored
- **WHEN** a coalition holds a `vision.report` with `item` "episode-01.mkv" and `item_order` 1
- **THEN** the stored trace holds `item_order` 1 and no "episode-01"

#### Scenario: Own speech keeps its words without its rendering
- **WHEN** a coalition holds `external_speech` with `text` and a `faithful_rendering` that renders an `item`
- **THEN** the stored trace holds the `text` and no `faithful_rendering`

### Requirement: Audited own-content pairs keep only their allowlisted fields
`kaine/faithful/episodic_own_content.py` SHALL declare, for the episodic store only, a field allowlist for each pair in the design's own-content audit; `EPISODIC_OWN_CONTENT` SHALL be `INTERNAL_EVENT_TYPES` plus those pairs. For a member of an audited pair that is not heard, the trace text SHALL hold only the fields its allowlist names whose values pass the field's rule, after `strip_vectors`; every other field SHALL be dropped.

#### Scenario: A belief keeps its label and numbers
- **WHEN** a broadcast's coalition holds `planning.belief` with `statement` `salience_high`, `kind`, `frequency` and `confidence`
- **THEN** the stored trace text holds those four fields

#### Scenario: An exception message is not stored
- **WHEN** a coalition member is `planning.error` whose `error_reason` quotes "meet me at 12 Elm Street"
- **THEN** the stored trace holds `elapsed_ms`, `num_factors` and `num_actions` and no "Elm Street"

#### Scenario: A field the producer adds later is dropped
- **WHEN** a member of an audited pair carries a field `message` that its allowlist does not name
- **THEN** the stored trace holds the member's allowlisted fields and no `message`

#### Scenario: A value outside its field's rule is dropped
- **WHEN** a `perceptual_locus.denied` member's `requested` is a sentence rather than a locus
- **THEN** the stored trace holds `reason` and no `requested`

#### Scenario: The heard rule runs first
- **WHEN** a member of an audited pair carries a non-empty `heard_text` field
- **THEN** the stored trace holds `source:type=<heard omitted>`

### Requirement: The allowlist rules admit no free text and leave the organ's layout alone
No field rule SHALL admit a string outside a fixed set of values, a trace-id format or a token of at most 64 characters from `[A-Za-z0-9_.:-]`. No allowlist SHALL name a heard-text field or a field the audit classed as heard-derived. The language module SHALL NOT read the declaration, and it SHALL change neither `INTERNAL_EVENT_TYPES` nor the prompt layout digest.

#### Scenario: A sentence in a token field is dropped
- **WHEN** a `social_cognition.agent_model` member's `agent_label` is "Alice Smith"
- **THEN** the stored trace holds no `agent_label`

#### Scenario: The organ's layout is unchanged
- **WHEN** the declaration is imported
- **THEN** `layout_digest()` is `76f99c859fe8b7bb` and `INTERNAL_EVENT_TYPES` holds the same 18 pairs

### Requirement: Existing stores can be checked for heard text without reading it out
A read-only maintainer tool SHALL report, for sqlite-vec and Qdrant stores, fork snapshots and preservation bundles, how many traces it read, how many hold a member that may carry heard text (an external-input member with a payload, a heard-text field, text in an undeclared type or outside an audited pair's allowlist, or an unreadable payload holding a string) and those traces' ids. It SHALL print no trace text and change nothing it reads.

#### Scenario: An audited pair's current trace is clean
- **WHEN** a trace holds a `planning.belief` member whose every field passes its rule
- **THEN** the tool does not flag it, and it flags a legacy `planning.error` member that kept `error_reason` text

#### Scenario: A legacy chat trace is reported by id only
- **WHEN** a store holds a trace written before the heard rule with an `embodiment.chat` member holding "hello there"
- **THEN** the report counts it, names its id, and contains no "hello there", and the store's files are unchanged

### Requirement: New traces store their members
Each trace stored after this change SHALL carry `members`: for each coalition member its `source`, `type`, `accessed`, `intensity` and `fields`, the payload keys the felt renderer declares for that type, after `strip_vectors`. Traces stored before this change SHALL NOT be rewritten.

#### Scenario: A vision member keeps its felt fields only
- **WHEN** an accessed vision report with `change_score`, `habituation_score` and a 768-component `latent` is stored
- **THEN** its member entry holds `change_score` and `habituation_score`, `accessed` true, and no `latent`

#### Scenario: An old trace keeps its form
- **WHEN** a store holding traces without `members` is opened
- **THEN** those traces are read as they are and no member list is derived from their text

### Requirement: The live recall searches the persisted store with a recency exclusion
The live recall SHALL search the persisted episodic collection and the short-term buffer, ranked by strength times similarity with short-term traces at strength 1, and SHALL leave out short-term traces stored within the last `recall_exclude_recent_s` entity seconds, default 30.

#### Scenario: A trace from an earlier wake can be recalled
- **WHEN** the best match for a cue is a persisted trace stored two sleeps ago
- **THEN** the recall returns it first

#### Scenario: The last half minute is not recalled
- **WHEN** the most similar trace was stored 10 entity seconds ago
- **THEN** the recall does not return it

### Requirement: Recall content comes from the best trace's accessed members
With `recall_content` true, `content` SHALL hold the best-ranked trace's accessed members, at most `recall_render_max` (default 3) in stored order, each as `source`, `type` and `fields`; an `age_band` of `this_wake`, `last_wake` or `earlier` from the trace's `born_sleep`; and `trace_ref`. A schema node, a trace without `members`, or a trace with no accessed member SHALL yield no `content`. Before publishing, the heard rule and `strip_vectors` SHALL be applied to `content` again.

#### Scenario: Content from an accessed own thought
- **WHEN** the best trace's accessed members are a language thought with text "the light keeps changing" and an affect state
- **THEN** `content.members` holds both with their fields and `content.age_band` is set from the trace's sleep count

#### Scenario: A legacy trace yields familiarity only
- **WHEN** the best trace has no `members`
- **THEN** the event carries `top_similarity` and no `content`

### Requirement: The live path is tested end to end without an entity
A test SHALL run the episodic memory module, the workspace and the language context assembler with no organ and no entity, plant a distinctive own thought in an early broadcast, cue it later, and check that the accessed recall's rendering in the assembled notes contains the planted words with `recall_content` true and does not with it false.

#### Scenario: A planted thought comes back
- **WHEN** the harness plants the thought "the light keeps changing", moves it to the persisted collection and cues a related thought
- **THEN** the assembled notes hold a line beginning "I remember" that contains "the light keeps changing"
