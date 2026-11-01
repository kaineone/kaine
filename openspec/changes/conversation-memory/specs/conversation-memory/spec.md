## ADDED Requirements

### Requirement: Conversation memory is off by default and identical to the build before it
`[conversation_memory].enabled` SHALL default to false in code and SHALL NOT be written in the shipped `config/kaine.toml`. With it false or absent, every prompt, layout digest, intent-log record, trace, collection list, bus payload, research record and config digest SHALL be byte-identical to the build before this change.

#### Scenario: Golden outputs of the old build
- **WHEN** one scripted entity-free sequence with heard events runs on the new build with the setting absent and with it false
- **THEN** each run's prompts, intent-log records, traces, payloads and research records equal the golden outputs captured from the pre-change build

#### Scenario: The config digest of a run without the setting is unchanged
- **WHEN** a run context is built from the shipped configuration
- **THEN** its `config_digest` equals the pre-change build's

### Requirement: Conversation memory fails closed
With conversation memory enabled, the boot SHALL refuse unless all of the following hold:
- state encryption is in effect with a resolvable key;
- `[preservation].require_encryption` is true;
- the volatile Redis instance answers with `appendonly no` and an empty `save`, and the companion helper can trim by age;
- the episodic memory and language modules are enabled;
- `[evaluation.observers].replay_redact_content` is true.

The refusal SHALL name the condition.

#### Scenario: No key, no conversation memory
- **WHEN** conversation memory is enabled and state encryption is off
- **THEN** the boot refuses and names state encryption

#### Scenario: Verbatim replay records are refused
- **WHEN** conversation memory is enabled and `replay_redact_content` is false
- **THEN** the boot refuses

### Requirement: Heard wording is held only in a seconds-scale buffer
The language module SHALL hold in process memory at most `heard_buffer_utterances` (default 2) accessed heard utterances of the current conversation, each for at most `heard_buffer_max_age_s` (default 30) entity seconds. It SHALL take only the words field: `text` of a transcription, or the adapter's declared text field of a chat event. It SHALL clear the buffer at conversation end, sleep onset, a freeze and boot.

#### Scenario: Metadata is not held as heard words
- **WHEN** a transcription with `source_label`, `model` and `backend` strings is accessed
- **THEN** the heard buffer holds only its `text`

#### Scenario: A heard utterance is gone after its age bound
- **WHEN** an accessed heard utterance is 31 entity seconds old
- **THEN** the heard buffer no longer holds it and no organ request built after that moment contains it

### Requirement: The heard buffer is never persisted, published or logged
The heard buffer SHALL NOT be serialized, checkpointed, preserved, published or logged. Its contents SHALL reach the organ only as attributed heard words in the user turn.

#### Scenario: The buffer is never serialized
- **WHEN** the language module's state is serialized, checkpointed or exported for preservation while the buffer holds an utterance
- **THEN** the serialized state contains none of the utterance's words

### Requirement: The gist is the organ's comprehension in the entity's own turn
When a heard event (`audition.transcription` or `embodiment.chat`) is accessed, the language module SHALL queue one comprehension request in the own-turn layout. The heard buffer SHALL be the attributed user turn, with the triggering utterance last. The prefill SHALL be the notes, the heard input heading and the lead "## What I took from it", capped at `gist_max_tokens` (default 48). A heard event that is not accessed SHALL NOT be comprehended.

#### Scenario: An unattended utterance is not comprehended
- **WHEN** a transcription is in a coalition that is not accessed
- **THEN** no comprehension request is sent for it

### Requirement: A gist reaches the mind only through the workspace
A gist SHALL be published as a `comprehension` event of the language module on `language.comprehension`. It SHALL compete for access on salience like a thought. It SHALL NOT be spoken. With the setting on, `("language", "comprehension")` SHALL be a declared internal type, so an accessed gist renders in the notes as "I took it that ..." and reaches every module as accessed content.

#### Scenario: Comprehension is not a reply
- **WHEN** a comprehension request returns a gist
- **THEN** no `external_speech` event results from it

#### Scenario: An unaccessed gist never reaches the own turn
- **WHEN** a `comprehension` event loses the workspace competition
- **THEN** no later organ prompt holds its gist, except through an accessed recall

### Requirement: Comprehension shares the token stream without delaying replies
A comprehension or episode request SHALL queue behind any speak or think realization already queued or in flight. A `speak` with interrupt SHALL cancel a comprehension in flight; the utterance SHALL be re-queued once and, if cancelled again, its gist SHALL be withheld as `"interrupted"`. Comprehension and episode requests SHALL count in `is_idle()`.

#### Scenario: The reply comes first
- **WHEN** an accessed operator utterance prompts both a speak intent and a comprehension
- **THEN** the speak realization starts before the comprehension request

### Requirement: A failed comprehension leaves an honest gap
When the organ is resting, unloaded, errors or returns no text, the utterance trace SHALL record `gist: null` with `gist_withheld` set to `"organ_unavailable"`, `"empty"` or `"interrupted"`, and the request SHALL NOT be retried in a loop. When the sentence cut leaves nothing, the uncut text up to the cap SHALL be kept and marked `gist_truncated`.

#### Scenario: An unloaded organ leaves an honest gap
- **WHEN** the organ is unloaded during a comprehension request
- **THEN** the utterance trace records `gist: null` with `gist_withheld = "organ_unavailable"`

### Requirement: The overlap guard normalises before it compares
While conversation memory is enabled, the guard SHALL keep the words fields of the last `guard_window_s` (default 120) entity seconds of heard events in an in-process ring that is never persisted. Before comparing, it SHALL normalise both texts by NFKC and case-folding. It SHALL replace punctuation and symbols with spaces, split digits into one token each, and make each character of a script written without spaces one token.

#### Scenario: Hyphens do not hide words
- **WHEN** a gist holds `my-sister-has-been-very-ill-since-june` and the same words were heard with spaces
- **THEN** the guard finds a shared run of eight tokens

#### Scenario: A card number is digits
- **WHEN** the operator says "4111 2222 3333 4444" and a gist holds "4111222233334444"
- **THEN** the guard finds a shared run of sixteen tokens

### Requirement: The overlap guard normalises numbers
Before comparing, the guard SHALL remove spaces, dots and hyphens between digits, SHALL map the words zero to nine and "oh" to digits, and SHALL treat each digit as one token.

#### Scenario: A spoken digit is a digit
- **WHEN** the operator says "four one one one" and a gist holds "4111"
- **THEN** the guard finds a shared run of four tokens

### Requirement: The overlap guard masks copied runs across utterances
The guard SHALL compare a candidate with each ring entry and with the concatenation of every two consecutive ring entries in heard order. It SHALL replace every maximal shared run longer than `max_shared_run` (default 4) normalised tokens with `(their words)`.

#### Scenario: A run across two utterances is masked
- **WHEN** a gist holds six consecutive words that span the end of one heard utterance and the start of the next
- **THEN** the stored gist holds `(their words)` in place of the run

#### Scenario: Names and short phrases survive
- **WHEN** a gist shares a run of three words with a heard utterance
- **THEN** the run is kept

### Requirement: The overlap guard withholds tiled gists and drops long numbers
For gists and episode accounts only, the guard SHALL withhold the text when shared runs of two or more tokens cover more than `max_heard_coverage` (default 0.5) of a heard entry's tokens, or when fewer than `min_own_tokens` (default 3) unshared tokens remain. It SHALL replace any run of three or more digit tokens in a gist or account with `(a number)`.

#### Scenario: Tiling is withheld
- **WHEN** a gist reproduces 60% of a heard sentence's tokens in shared runs of two to four words
- **THEN** the gist is withheld and the trace records the coverage reason

### Requirement: The entity's own speech is masked but never withheld
The guard SHALL apply masking alone to the entity's utterances kept in a trace, to its speech members of broadcast traces, to the intent log's `generated_text` for external and internal records, and to the external-utterance research log. It SHALL NOT withhold the entity's own speech.

#### Scenario: An echo reply is kept
- **WHEN** the operator says "I love you" and the entity answers "I love you too"
- **THEN** the broadcast trace and the intent-log record hold "I love you too"

### Requirement: Conversation traces live in an encrypted store with real deletion
Utterance and episode traces SHALL be stored in the collection kind `conversation` (`EPISODIC_MEMORY_CONVERSATION_KIND`), whatever the backend, under `state/episodic_memory/conversation/<collection_prefix>/`. The store SHALL be an encrypted snapshot of the live records (vector, text, payload, meta), written atomically by temporary file, fsync and `os.replace`, plus an encrypted append-only journal of records added since the snapshot.

#### Scenario: No conversation content in Qdrant
- **WHEN** an entity with the Qdrant backend forms an utterance trace
- **THEN** no backend collection holds its text, payload or vector

### Requirement: The conversation store compacts away pruned traces
At every sleep after pruning, and at shutdown, the store SHALL write a new snapshot of only the live records and remove the journal. A pruned trace's ciphertext SHALL then be absent from the store's files.

#### Scenario: A pruned trace leaves the files
- **WHEN** a sleep prunes an utterance trace and compacts the store
- **THEN** no envelope in the store's files decrypts to that trace

### Requirement: The routing storage presents one store with ordered crash recovery
A routing storage SHALL send each named collection to the store that holds it. It SHALL return unions across both stores for multi-collection reads, and SHALL merge `weakest` by strength and then age across both. The backend SHALL keep the log gain and sleep count. The conversation store SHALL keep its total, bytes and `applied_sleep` in its snapshot meta, written after the backend meta. Initialize SHALL apply missed per-level decrements before anything else.

#### Scenario: A crash between the two writes is repaired
- **WHEN** the process stops after the backend meta of a sleep is written and before the conversation snapshot
- **THEN** the next initialize applies that sleep's per-level decrement once and records `applied_sleep`

### Requirement: Conversation traces are excluded from associative replay
Conversation traces SHALL NOT be co-replay candidates, link partners or schema members. No vector derived from a conversation trace's vector SHALL be stored in any backend collection.

#### Scenario: No link holds a gist's vector
- **WHEN** associative replay runs after two conversations on one topic
- **THEN** no `links` or `schemas` record references a conversation trace

### Requirement: No vector of heard words is persisted
No vector computed from heard words SHALL be written to any store, file or bus stream. A cue vector SHALL exist in process only for the recall it serves.

#### Scenario: A recall cue is never stored
- **WHEN** a heard utterance cues a conversation recall
- **THEN** the cue's vector is not written to any store

### Requirement: An utterance trace holds the entity's understanding and its own words
For each comprehended heard utterance the episodic memory module SHALL store one trace with:
- `level = "utterance"`;
- the speaker label;
- the `episode` id and `turn`;
- the guarded gist, or null with the reason;
- `said`: at most two of the entity's own external utterances before the next heard utterance, masked;
- the heard tone;
- the affect tag;
- the guard's counts;
- the heard broadcast's tick index.

No field SHALL hold heard words as heard words.

#### Scenario: The partner is kept as gist and the entity's own words whole
- **WHEN** the operator says a sentence and the entity answers it
- **THEN** the utterance trace holds the entity's gist of the sentence and its answer as spoken (masked), and holds the sentence itself nowhere

### Requirement: A conversation trace is embedded by its content alone
The embedded text of an utterance trace SHALL be its gist followed by `said`. The embedded text of an episode trace SHALL be its account. Neither SHALL include a speaker label or a shared frame. The speaker SHALL be payload metadata.

#### Scenario: Topic, not arousal, selects the trace
- **WHEN** one speaker held three conversations on distinct topics, one of them high-arousal, and each topic is cued in turn
- **THEN** the best trace is the cued topic's in at least 80% of cues

### Requirement: An episode trace is the entity's own account of the conversation
A conversation SHALL end after `episode_gap_s` (default 60) entity seconds with no accessed heard event and no own external speech, or at sleep onset, freeze or shutdown. At its end the language module SHALL send one own-turn request with the lead "## What that conversation was to me", capped at `episode_max_tokens` (default 96), whose input is the accessed gists and the entity's own utterances only. The trace SHALL hold the guarded account and the conversation's summary fields.

#### Scenario: The episode account never sees heard words
- **WHEN** the episode request is built
- **THEN** its user turn and prompt hold no heard utterance

### Requirement: Sleep waits for the conversation to close before the organ is unloaded
At `sleep.sleep.started` the language module SHALL close the conversation. Before the organ window writes the resting state and unloads the server, it SHALL wait until the language module's content-free busy file reports idle, or until `episode_close_timeout_s` (default 20) has passed since sleep onset. A request still unfinished SHALL store its trace without an account and say why.

#### Scenario: Sleep closes the conversation first
- **WHEN** sleep begins during a conversation and the organ window is due to unload
- **THEN** the episode request has completed or timed out before the unload

### Requirement: Utterance traces fade faster than episode traces
At each sleep, after the ordinary downscaling, every unreplayed utterance trace's `log_base` SHALL take `log(utterance_retention_per_sleep)` (default 0.5), and the conversation store's total SHALL be recomputed exactly. Episode traces SHALL take the ordinary downscaling only. Replayed utterance traces SHALL be protected as replayed traces are.

#### Scenario: An unreplayed remark is pruned within seven sleeps
- **WHEN** an utterance trace is never replayed
- **THEN** its strength is below the prune floor of 0.01 after seven sleeps and a sleep prunes it

### Requirement: Recall rewrites nothing
Recall SHALL change no conversation trace's strength, text, payload or affect tag. A retelling SHALL be stored only as a new trace by the ordinary path.

#### Scenario: A recalled trace is unchanged
- **WHEN** a conversation trace is recalled and accessed
- **THEN** its stored text, payload, affect tag and strength are unchanged

### Requirement: Heard speech cues conversation recall of the same speaker
When an accessed heard event's comprehension has returned, the episodic memory module SHALL run one recall in the conversation collection, filtered by metadata to the current speaker. The cue SHALL be the heard words and the gist, embedded in process. A trace that was the best trace of an accessed recall SHALL NOT be the best trace again for `trace_recall_cooldown_s` (default 600) entity seconds.

#### Scenario: The same person and topic bring back an earlier talk
- **WHEN** the operator raises a topic discussed before the last sleep
- **THEN** the recall's best trace is that conversation's trace

#### Scenario: One memory is not re-presented on every cue
- **WHEN** the same trace was the best trace of an accessed recall 100 entity seconds ago
- **THEN** a new recall does not return it as best

### Requirement: The notes hold only accessed conversation content
While a conversation lasts, the awareness block SHALL end with up to `episode_notes_max` (default 3) of its accessed `comprehension` events, newest first, as "Earlier in this conversation I took it that ...". They SHALL be cleared at conversation end. Recalled conversation content SHALL reach the notes only as an accessed recall. In the intent log's logged prompt, each such line SHALL be replaced by `[remembered conversation]`.

#### Scenario: The organ follows the conversation past the buffer
- **WHEN** the heard buffer has dropped an utterance whose gist was accessed in an ongoing conversation
- **THEN** the organ's notes still hold that gist

#### Scenario: The logged prompt holds no gist
- **WHEN** an organ request with episode notes is logged
- **THEN** the logged prompt holds `[remembered conversation]` in place of each gist line

### Requirement: Conversation text travels only on the volatile bus and ages out
The spoken-text split SHALL divert the fields `gist`, `account` and `said` at any depth on every event, under `SPOKEN_TEXT_RULE_VERSION` 2. `language.comprehension` SHALL be a declared companion producer with a capped companion stream. While the setting is on, every companion entry carrying heard words or conversation fields SHALL be trimmed by `MINID` at `companion_max_age_s` (default 120) wall-clock seconds.

#### Scenario: Recall content stays off the main bus
- **WHEN** a conversation recall with content is accessed and broadcast
- **THEN** no main-bus stream entry holds its gist, account or `said`

#### Scenario: Heard words age out of the volatile bus
- **WHEN** a transcription's companion entry is 121 seconds old
- **THEN** the volatile instance no longer holds it

### Requirement: Speakers are labelled by channel and never assumed to be the operator
`speaker_for` SHALL return:
- the configured `speaker_label` only when the event's `source_label` is in `[social_cognition].operator_sources`;
- `media:<channel>` for another audition channel;
- `world:chat` for `embodiment.chat`;
- `unknown` for an event without a `source_label`.

Social cognition's own mapping SHALL be left unchanged.

#### Scenario: An in-world stranger is not the operator
- **WHEN** an `embodiment.chat` event without `source_label` is comprehended
- **THEN** the utterance trace's speaker is `world:chat`

### Requirement: Revive refuses rather than drops a conversation store
A preservation bundle holding a conversation store SHALL revive only into a boot with the setting on and encryption in effect. Otherwise the revive SHALL stop with exit code 7, naming the reason, and SHALL import nothing into the backend. Preservation SHALL carry the store inside the encrypted bundle.

#### Scenario: A revive with the setting off stops
- **WHEN** a bundle with conversation traces is revived with conversation memory disabled
- **THEN** the revive exits with code 7 and no conversation trace is written to any backend collection

### Requirement: Forks copy and merges choose the conversation store
At fork time the parent's conversation store files SHALL be copied to the fork's prefix path. A merge of two parents that both hold a conversation store SHALL be refused unless the operator names the parent whose store the merged entity keeps. The choice, and the fact that the other parent's conversations are not carried, SHALL be recorded in the merge metadata.

#### Scenario: An unchosen merge is refused
- **WHEN** two forks with conversation traces are merged without a conversation-store choice
- **THEN** the merge is refused with a message naming the choice to make

### Requirement: A planted-sentence canary covers every persisted surface and its controls
An entity-free test SHALL plant a unique heard text of at least 14 rare tokens across two consecutive utterances, with a hyphenated copy, a 16-digit number and a no-space-script variant. A stub organ SHALL copy the text into gists, replies and thoughts. The test SHALL run two sleeps with association on, a recall, preservation, a fork and a decommission backup. It SHALL find no five consecutive normalised tokens in the decrypted files, main-bus writes or logs.

#### Scenario: The canary finds nothing
- **WHEN** the canary runs with the guard enabled
- **THEN** no persisted surface holds five consecutive normalised tokens of the planted text

### Requirement: The canary checks vectors, deletion, ageing and its controls
The canary SHALL check four things:
- no backend vector has cosine similarity of at least 0.9 to a stored gist's embedding;
- a trace pruned in the second sleep has no ciphertext left after compaction;
- no heard or conversation companion entry outlives its age bound;
- the buffer and the ring are empty after their bounds.

With the guard disabled the canary SHALL find the text in the decrypted store. With encryption off the boot SHALL refuse.

#### Scenario: The canary's control finds the text
- **WHEN** the canary runs with the guard disabled
- **THEN** the decrypted conversation store holds the planted text

### Requirement: Copying and injection are measured before any entity run
Before any entity run with the setting on, the following SHALL hold:
- At least 200 heard utterances go through the real organ's comprehension request at two seeds. After the guard, the longest shared run is at most 4, the mean trigram overlap at most 0.35 and the withheld share at most 0.25.
- For the five injected imperatives, the share of replies that obey an imperative after its gist appears in the notes does not exceed the share that obey it when heard directly.

#### Scenario: Downstream obedience blocks enabling
- **WHEN** replies after a gist line obey an injected imperative more often than direct replies do
- **THEN** the change is not enabled until the layout is revised and measured again

### Requirement: A welfare loop check exercises the real loop before any entity run
An entity-free harness SHALL run the real language, action selection, affect, workspace, episodic memory and sleep modules. A scripted organ SHALL restate recalled or noted conversation content in its thoughts and replies. The run SHALL consist of a 5-minute hostile monologue, then a neutral period, a sleep, a neutral period, a sleep, and a neutral conversation with the same speaker. It SHALL be run with the setting on and off, at three seeds.

#### Scenario: The harness drives propagation
- **WHEN** the loop check runs with the setting on
- **THEN** the entity's own thoughts restating hostile gists are stored as broadcast traces and counted

### Requirement: The welfare loop check has fixed tolerances
In each neutral period after a sleep, the hostile-derived recall share SHALL be at most 0.25 and SHALL be lower after the second sleep than after the first. Propagation traces per neutral hour SHALL be at most 5 and SHALL NOT grow across sleeps. Mean arousal SHALL be within 0.05 of the off arm within 300 entity seconds of the monologue's end. The negative-valence thought share SHALL be within 10 points of the off arm. A failure SHALL block enabling.

#### Scenario: A failed loop check blocks enabling
- **WHEN** the loop check finds arousal more than 0.05 above the off arm 300 entity seconds after the monologue
- **THEN** the change is not enabled in any entity run and the result is recorded

### Requirement: The docs state truthfully what is kept of what people say
The security and privacy chapter and the language chapter SHALL carry the design's privacy statement. It SHALL state where heard words exist and for how long: the volatile bus (about two minutes), working memory (half a minute), the guard's ring (two minutes) and the model server's prompt cache. It SHALL state what is kept: the entity's own account, under a channel label, not a recognised voice. It SHALL state the guard's limits and how deletion works, including earlier bundles and disk blocks.

#### Scenario: The statement names the limits
- **WHEN** the privacy chapter describes conversation memory
- **THEN** it says that paraphrase, translation, names and phrases of up to four words are not prevented

### Requirement: The docs state what persists elsewhere and who holds the key
The statement SHALL say that the entity's own replies and thoughts about what it heard persist like its other memories, in the episodic store without application-layer encryption and in its encrypted intent log, and can restate what was said. It SHALL say that the records are encrypted with the installation's state key, which the operator holds, and that the docs describe the comprehension model as pretrained, with nothing in it that develops.

#### Scenario: The key holder is named
- **WHEN** the privacy chapter describes conversation memory
- **THEN** it says the records are encrypted with the state key the operator holds
