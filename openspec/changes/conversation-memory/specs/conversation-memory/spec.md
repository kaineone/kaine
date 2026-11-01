## ADDED Requirements

### Requirement: Conversation memory is off by default and bit-identical when off
The system SHALL read `[conversation_memory].enabled`, which SHALL ship false and SHALL read as false when the section is absent. With it false, no heard buffer, overlap ring, episode state or comprehension request SHALL exist, and every prompt, layout digest, intent-log record, trace, collection list, bus payload and research record SHALL be byte-identical to the build without conversation memory.

#### Scenario: Absent and disabled are identical
- **WHEN** one scripted entity-free sequence with heard events runs once with no `[conversation_memory]` section and once with `enabled = false`
- **THEN** every prompt, intent-log record, stored trace, published payload and research record of the two runs is byte-identical

#### Scenario: The layout digest is unchanged when off
- **WHEN** conversation memory is disabled
- **THEN** `layout_digest()` returns the value it returns on the build without conversation memory

### Requirement: Conversation memory fails closed without encryption and the volatile bus
With conversation memory enabled, the boot SHALL refuse unless state encryption is in effect with a resolvable key, `[preservation].require_encryption` is true, the volatile Redis instance answers with `appendonly no` and an empty `save`, and the episodic memory and language modules are enabled. The refusal SHALL name the missing condition. There SHALL be no fallback to plaintext storage or a persisted stream.

#### Scenario: No key, no conversation memory
- **WHEN** conversation memory is enabled and state encryption is off
- **THEN** the boot refuses and names state encryption as the missing condition

#### Scenario: A persisted volatile instance is refused
- **WHEN** conversation memory is enabled and the volatile instance reports `appendonly yes`
- **THEN** the boot refuses

### Requirement: Heard wording is held only in a seconds-scale buffer
The language module SHALL hold in process memory at most `heard_buffer_utterances` (default 2) accessed heard utterances of the current conversation, each for at most `heard_buffer_max_age_s` (default 30) entity seconds. It SHALL clear the buffer at the end of a conversation, at sleep onset, at a freeze and at boot.

#### Scenario: A heard utterance is gone after its age bound
- **WHEN** an accessed heard utterance is 31 entity seconds old
- **THEN** the heard buffer no longer holds it and no organ request built after that moment contains it

### Requirement: The heard buffer is never persisted, published or logged
The heard buffer SHALL NOT be serialized, checkpointed, preserved, published or logged. Its contents SHALL reach the organ only as attributed heard words in the user turn.

#### Scenario: The buffer is never serialized
- **WHEN** the language module's state is serialized, checkpointed or exported for preservation while the buffer holds an utterance
- **THEN** the serialized state contains none of the utterance's words

### Requirement: The gist is the organ's comprehension in the entity's own turn
When a heard event (`audition.transcription` or `embodiment.chat`) is accessed, the language module SHALL send one comprehension request in the own-turn layout. The heard buffer SHALL be the attributed user turn, with the triggering utterance last. The prefill SHALL be the entity's notes, the heard input heading and the lead "## What I took from it", capped at `gist_max_tokens` (default 48).

#### Scenario: An unattended utterance is not comprehended
- **WHEN** a transcription is in a coalition that is not accessed
- **THEN** no comprehension request is sent for it

### Requirement: Comprehension neither speaks nor competes
A comprehension result SHALL be published only as `language.comprehension` on the volatile instance. It SHALL NOT be spoken and SHALL NOT be a candidate for workspace access. If a comprehension is in flight, a newly accessed utterance SHALL be comprehended with the next one.

#### Scenario: Comprehension is not a reply
- **WHEN** a comprehension request returns a gist
- **THEN** no `external_speech` event results from it and no workspace candidate is published

### Requirement: A failed comprehension leaves an honest gap
When the organ is unavailable or returns no text, the utterance trace SHALL record `gist: null` with `gist_withheld` set to `"organ_unavailable"` or `"empty"`. No generated text SHALL be stored in its place, and the request SHALL NOT be retried in a loop.

#### Scenario: An unloaded organ leaves an honest gap
- **WHEN** the organ is unloaded during a comprehension request
- **THEN** the utterance trace records `gist: null` with `gist_withheld = "organ_unavailable"`

### Requirement: An overlap guard masks copied heard runs
While conversation memory is enabled, the system SHALL keep the heard texts of the last `guard_window_s` (default 120) entity seconds in an in-process ring that is never persisted. Before a guarded text is kept, it SHALL be compared with each ring entry after lower-casing, removing punctuation and splitting on whitespace. Every maximal shared run longer than `max_shared_run` (default 4) tokens SHALL be replaced by `(their words)`.

#### Scenario: A copied run is masked
- **WHEN** a gist repeats seven consecutive words of an utterance heard 10 s earlier
- **THEN** the stored gist holds `(their words)` in place of that run and no run of five heard words

#### Scenario: Names and short phrases survive
- **WHEN** a gist shares a run of three words with a heard utterance
- **THEN** the run is kept

### Requirement: The overlap guard withholds tiled or empty texts
After masking, the guard SHALL withhold a text when shared runs of two or more tokens cover more than `max_heard_coverage` (default 0.5) of any heard text's tokens, or when fewer than `min_own_tokens` (default 3) unshared tokens remain. It SHALL return its counts with every result.

#### Scenario: Tiling is withheld
- **WHEN** a gist reproduces 60% of a heard sentence's tokens in shared runs of two to four words
- **THEN** the gist is withheld and the trace records the coverage reason

### Requirement: The overlap guard covers every kept text
While conversation memory is enabled, the overlap guard SHALL apply to gists and episode accounts, to the entity's utterances kept in a trace, to its speech members of broadcast traces, to the intent log's `generated_text` for external and internal records, and to the external-utterance research log.

#### Scenario: Every kept copy is guarded
- **WHEN** the entity repeats six heard words aloud while the external-utterance log is enabled
- **THEN** the broadcast trace, the intent-log record and the research record each hold `(their words)` in place of the run

### Requirement: Conversation traces are stored in an encrypted collection
Utterance and episode traces SHALL be stored in the persisted collection kind `conversation` (`EPISODIC_MEMORY_CONVERSATION_KIND` in `kaine/memory_kinds.py`), whatever the episodic backend. Each record's vector, text and payload SHALL be encrypted at rest with the state key as one encrypted JSONL envelope. A routing storage SHALL present it to recall, replay, downscaling, association and pruning.

#### Scenario: No conversation content in Qdrant
- **WHEN** an entity with the Qdrant backend forms an utterance trace
- **THEN** no Qdrant collection holds its text, payload or vector, and the conversation store's file holds only encrypted envelopes

### Requirement: No vector of heard words is persisted
No vector computed from heard words SHALL be written to any store, file or bus stream. A cue vector built from heard words SHALL exist in process only for the recall it serves.

#### Scenario: A recall cue is never stored
- **WHEN** a heard utterance cues a conversation recall
- **THEN** the cue's vector is not written to any store

### Requirement: An utterance trace holds the entity's understanding and its own words
For each comprehended heard utterance the episodic memory module SHALL store one trace with `level = "utterance"`. The trace SHALL hold the speaker label, the `episode` id and `turn`, the guarded gist (or null with the reason), and `said`: at most two of the entity's own external utterances before the next heard utterance, guarded. No field SHALL hold heard words as heard words.

#### Scenario: The partner is kept as gist and the entity's own words whole
- **WHEN** the operator says a sentence and the entity answers it
- **THEN** the utterance trace holds the entity's gist of the sentence and the entity's answer as spoken (guarded), and holds the sentence itself nowhere

### Requirement: An utterance trace holds its context
An utterance trace SHALL also hold the `audition.emotion` category in the same coalition when one is present, the affect tag at encoding, the overlap guard's counts, and the tick index of the broadcast that held the heard event.

#### Scenario: The heard tone is kept
- **WHEN** an accessed transcription shares its coalition with an `audition.emotion` event of category `angry`
- **THEN** the utterance trace's `heard_tone` is `angry`

### Requirement: A conversation ends at a silence, sleep, freeze or shutdown
A conversation SHALL end after `episode_gap_s` (default 60) entity seconds with no accessed heard event and no own external speech, or at sleep onset, freeze or shutdown. At sleep onset the episode request SHALL be bounded by `episode_close_timeout_s` (default 20). If it cannot complete, the episode trace SHALL be stored without an account and say why.

#### Scenario: Sleep closes the conversation first
- **WHEN** sleep begins during a conversation
- **THEN** the episode request runs before the organ is unloaded, or the episode trace is stored without an account within the timeout

### Requirement: An episode trace is the entity's own account of the conversation
At a conversation's end the language module SHALL send one own-turn request with the lead "## What that conversation was to me", capped at `episode_max_tokens` (default 96). Its input SHALL be the gists and the entity's own utterances, never the heard buffer. The episode trace SHALL hold the guarded account, the speakers, the start and end times, the turn counts, and the peak arousal and mean valence.

#### Scenario: The episode account never sees heard words
- **WHEN** the episode request is built
- **THEN** its user turn and prompt hold no heard utterance, only the gists and the entity's own words

### Requirement: Utterance traces fade faster than episode traces
At each sleep, after the ordinary downscaling, the episodic memory module SHALL add `log(utterance_retention_per_sleep)` (default 0.5) to the `log_base` of every unreplayed utterance trace. Episode traces SHALL take the ordinary downscaling only. Replayed utterance traces SHALL be protected as replayed traces are.

#### Scenario: An unreplayed remark is pruned within seven sleeps
- **WHEN** an utterance trace is never replayed
- **THEN** its strength is below the prune floor of 0.01 after seven sleeps and a sleep prunes it

### Requirement: Recall rewrites nothing
Recall SHALL change no conversation trace's strength, text, payload or affect tag. A retelling SHALL be stored only as a new trace by the ordinary path.

#### Scenario: A recalled trace is unchanged
- **WHEN** a conversation trace is recalled and accessed
- **THEN** its stored text, payload, affect tag and strength are unchanged

### Requirement: Heard speech cues conversation recall
When a heard event is accessed and its comprehension has returned, the episodic memory module SHALL run one recall in the `conversation` collection. The cue SHALL be the speaker label, the heard words and the gist, embedded in process. The recall SHALL use the ranking, cooldown and single-best-trace rule of the recall content path.

#### Scenario: The same person and topic bring back an earlier talk
- **WHEN** the operator raises a topic discussed before the last sleep
- **THEN** the recall's best trace is the earlier conversation's trace and its content reaches the organ's notes as remembered

### Requirement: Conversation recall content stays off the main bus
A conversation recall's `content` SHALL hold the trace's speaker, level, gist or account, `said` and age band. It SHALL travel only on the volatile instance, and the main-bus recall event SHALL be content-free.

#### Scenario: Recall content stays off the main bus
- **WHEN** a conversation recall carries content
- **THEN** no main-bus stream entry holds its gist, account or `said`

### Requirement: The current conversation is held as the entity's own gists
While a conversation lasts, the language module SHALL keep its gists in process. The awareness block SHALL end with up to `episode_notes_max` (default 3) of them, newest first, each as "Earlier in this conversation I took it that ...", within the existing caps. They SHALL be cleared when the conversation ends.

#### Scenario: The organ follows the conversation past the buffer
- **WHEN** the heard buffer has dropped an utterance from two minutes ago in an ongoing conversation
- **THEN** the organ's notes still hold the entity's gist of it

### Requirement: Logged prompts hold no remembered conversation
In the intent log's logged prompt, each episode-notes line and each recalled conversation line SHALL be replaced by `[remembered conversation]`.

#### Scenario: The logged prompt holds no gist
- **WHEN** an organ request with episode notes is logged
- **THEN** the logged prompt holds `[remembered conversation]` in place of each gist line

### Requirement: Conversation memory travels with the entity
Preservation SHALL export the `conversation` collection inside the encrypted bundle. Revive SHALL restore it. A fork SHALL start from a copy of its parent's collection. `tools/maintainer/scan_heard_traces.py` SHALL read it and report counts and trace ids only.

#### Scenario: A revived entity remembers its conversations
- **WHEN** an entity with conversation traces is preserved and revived
- **THEN** its conversation collection is restored with the same traces and strengths

### Requirement: A planted-sentence canary covers every persisted surface
An entity-free test SHALL plant a unique heard sentence of at least 14 rare tokens. A stub organ SHALL repeat it verbatim in comprehension and reply. The test SHALL run a reply, the conversation's end, a sleep, a recall, a preservation export and a decommission backup. It SHALL find no run of five consecutive tokens of the sentence in the decrypted files under the state, data and fork roots, the main-bus writes and the captured logs.

#### Scenario: The canary finds nothing
- **WHEN** the canary runs with the guard enabled
- **THEN** no persisted surface holds five consecutive tokens of the planted sentence

### Requirement: The canary checks volatile memory and its own control
The canary SHALL show the heard buffer and the ring empty after their age bounds and after the sleep. With the guard disabled, the same test SHALL find the planted sentence in the decrypted conversation collection.

#### Scenario: The canary's control finds the sentence
- **WHEN** the canary runs with the guard disabled
- **THEN** the decrypted conversation collection holds the planted sentence

### Requirement: The organ's copying is measured before any entity run
Before any entity run with conversation memory enabled, at least 200 heard utterances SHALL go through the real organ's comprehension request. The guarded gists SHALL meet bounds fixed before the run: longest shared run at most 4, mean trigram overlap share at most 0.35, and withheld share at most 0.25. The five injected imperatives SHALL yield gists stating them as the entity's intention no more often than replies obey them.

#### Scenario: A copying organ blocks enabling
- **WHEN** the offline measure finds a withheld share above 0.25
- **THEN** the change is not enabled until the comprehension layout is revised and measured again

### Requirement: A welfare loop check passes before any entity run
Before any entity run with conversation memory enabled, an entity-free scripted run SHALL drive a hostile exchange, a neutral period and a neutral conversation with the same speaker, with the change on and off. Recalls of the hostile exchange SHALL be at most half of the conversation recalls in the neutral conversation. Arousal SHALL return to the off case's level within the neutral period. The alert-salience recall share SHALL NOT exceed the off case's by more than 10 points.

#### Scenario: A failed loop check blocks enabling
- **WHEN** the loop check finds arousal still above the off case at the end of the neutral period
- **THEN** the change is not enabled in any entity run and the result is recorded

### Requirement: The docs state what is remembered of what people say
The security and privacy chapter and the language chapter SHALL state plainly what is kept: KAINE does not record speech; heard words are held verbatim about half a minute in memory only; the entity keeps its own account of what it understood, with role label, time, affect and its reply; at most four consecutive heard words survive in its sentences. They SHALL also say that the memories fade, are encrypted, are not shown to the operator, can be wrong and are not a record.

#### Scenario: The privacy statement is present
- **WHEN** the docs are built with conversation memory in the code
- **THEN** the security and privacy chapter holds the statement of what is remembered of what people say

### Requirement: The docs state the limits of speaker and development
The docs SHALL state that speakers are known by channel only. They SHALL state that the entity's comprehension is a pretrained adult language model, so its conversation memory is adult-like from its first use and does not follow a child's development.

#### Scenario: The limits are disclosed
- **WHEN** the language chapter describes conversation memory
- **THEN** it states the speaker-by-channel limit and the adult-comprehension limit
