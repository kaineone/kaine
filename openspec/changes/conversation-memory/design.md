# Design: remembering conversations as the entity understood them

Code facts are cited at `origin/main` d7fabdc0. The evidence is in the conversation-memory research notes of 2026-11-01; their section numbers are cited as R§n. The notes give each source's reading status, and every DOI in them was checked against Crossref on 2026-11-01.

## Context

### What exists

- **Heard words reach the organ only in the current coalition.** An accessed `audition.transcription` (payload `text`, `source_label`: `kaine/modules/audition/module.py:999-1012`) is classified as heard by the shared rule (`kaine/faithful/external_input.py:99-138`). The assembler builds it into `heard_turn`, the attributed user message ("Someone else said, in their words and not mine: ..."; `kaine/modules/language/context.py:98-107, 495`). The notes say only "Someone else spoke to me." Nothing holds heard words after the event leaves the coalition.
- **Transcription is off in the first configuration** (`config/kaine.toml:1012`). With it off, speech reaches the entity as sound only.
- **The episodic store keeps no heard words** (#636): a heard member is stored as `source:type=<heard omitted>` (`kaine/modules/episodic_memory/module.py:583, 654`). The entity's own speech is stored as spoken. The docs name the known limit: heard words the entity repeated are stored as its own (`docs/09-modules/episodic-memory.md:197`; `docs/09-modules/language.md:82`).
- **The intent log** records the organ's text unredacted (`generated_text=text`, `kaine/modules/language/module.py:1058-1061`). It redacts heard strings out of the prompt, the renderings and the heard turn only by exact match (`module.py:1003-1023`). The external-utterance research log records each `external_speech` text when enabled (spec `research-event-log`).
- **Who spoke** is known by channel only. Social cognition maps an operator channel, or an event with no channel, to `[social_cognition].speaker_label` (default `"operator"`, `config/kaine.toml:1508`) and any other channel to `media:<channel>` (`kaine/modules/social_cognition/module.py:180-190`). There is no voice-identity model.
- **The store is not encrypted at the application layer.** Qdrant collections hold vectors and payloads in plaintext behind an API key (`docs/13-security-and-privacy.md:72`). The application-layer AES-256-GCM record primitive exists for JSONL (`kaine/persistence/encrypted_jsonl.py:34, 135`).
- **Strength and sleep.** Persisted traces carry a strength `exp(log_base + L)` (`kaine/modules/episodic_memory/memory.py:130-135`). Each sleep:
  - phase 1 consolidates (`kaine/modules/sleep/phases.py:135`);
  - phase 2 replays the wake's traces by affect and recency (`phases.py:231`) and downscales every unreplayed trace by `retention_per_day ** (N_new / N_day)` (`phases.py:278-280`; `memory.py:594`);
  - associative replay (off by default) links similar traces of different wakes and forms schema nodes;
  - pruning removes traces below the floor and over budget.

  Recall changes no strength (spec `episodic-memory`). Replay events carry the trace text on the bus (`module.py:355`).
- **Related designs, not redone here.**
  - `episodic-recall-content` (in `openspec/changes/` on main) gives recall a content path: members in traces, `content` in the recall event, past-tense rendering, familiarity, and a welfare loop check. Its first PR, the shared heard rule, is built (#636). This change renders conversation traces through that content path.
  - `working-memory-store` (branch `spec/latent-workspace-memory-2026-10-31`) holds accessed members for up to 30 s and renders a held heard event as "Someone else spoke to me.". The heard buffer here is the language module's own and does not change that store.
  - `semantic-memory-store` is a later store of abstractions. Episode traces could feed it; that is not designed here.
  - `latent-content-privacy` (branch `spec/content-code-2026-10-31`) fixes the persisting surfaces, the volatile Redis instance and the identity-bound class.
  - Decision 2 of 2026-11-01 (the architecture decisions of 2026-11-01) puts heard text and the entity's utterance text on that volatile instance only. That work (operator speech as perception, the heard-text volatile bus) is being written now. This change depends on it and does not specify it again.

### What the science says, in brief

These points are from the research report:

1. **Wording lasts seconds.** Exact wording survives about the current sentence or two. Recognition of a syntactic change falls to chance after 80 to 160 syllables (Sachs 1967), and verbatim recall covers the clause and sentence just heard (Jarvella 1971) (R§1).
2. **The situation model lasts.** What lasts is the listener's model of the situation; surface form decays first, then the textbase (Kintsch et al. 1990). Whether this needs separate rates is disputed (Anderson, Budiu and Reder 2001) (R§1, R§5).
3. **Free recall is sparse.** About a tenth of idea units are recalled after five minutes and a few percent after days. What is recalled is mostly accurate, but wording, details and sources are reconstructed (Brown-Schmidt and Benjamin 2018; Neisser 1981) (R§2).
4. **Speaking beats hearing.** People remember their own contributions better than their partner's (McKinley et al. 2017; Yoon et al. 2021; Zormpa et al. 2023; the production effect) (R§3).
5. **Source fades first.** Memory of who said what is forgotten faster than the content (review) (R§3).
6. **Some wording survives.** Short, interactionally loaded or distinctive remarks can keep their wording for days (Keenan et al. 1977, 30 h; Kintsch and Bates 1977; Gurevich et al. 2010). The evidence is mostly for recognition, not recall (R§2).
7. **Events structure memory.** Event boundaries drive encoding (Zacks et al. 2007; Baldassano et al. 2017) (R§5).
8. **Emotion keeps the core.** Emotion preserves the central content and its detail; the periphery is lost (Kensinger et al. 2007) (R§6).
9. **Sleep's effect is moderate.** The benefit is g = 0.28 after correcting for selective reporting (Berres and Erdfelder 2021). Gist extraction in sleep is a hypothesis. Sleep neither preferentially consolidates emotional memory overall nor dampens its affect (Lipinska et al. 2019, 2022) (R§8).
10. **Human reconsolidation is contested** (Elsey et al. 2018; Hardwicke et al. 2016). Retrieval strengthening (the testing effect) and reconstruction over delay (Bergman and Roediger 1999) are robust (R§9).
11. **Mood-congruent recall is a documented loop.** Repetitive negative thought prolongs low mood. The fading affect bias is robust in populations, but its mechanism is unknown (R§10).
12. **Infants keep forms, not episodes.** Infants keep word forms, voices, prosody and regularities. Episodic memory of who said what comes later and stays fragile in childhood (R§11).
13. **Embeddings give the text back.** A text embedding can be inverted to recover the text: 92% of 32-token inputs exactly in-domain (Morris et al. 2023) (R§12).

## Decisions

### 1. Three levels, each with its own place and lifetime

| Level | Human analogue | What it holds | Where | Lifetime |
|---|---|---|---|---|
| Heard buffer | the auditory store and episodic buffer; "the current sentence or two" (points 1, R§4) | the last `heard_buffer_utterances` (default 2) accessed heard utterances of the current conversation, verbatim | language module process memory | `heard_buffer_max_age_s` (default 30 entity s) each; cleared at conversation end, sleep onset, freeze and boot |
| Utterance trace | the textbase: what was said, as understood (point 2) | the entity's gist, speaker, time, affect at encoding, heard tone, what the entity said back | `conversation` collection, encrypted | ordinary downscaling plus `utterance_retention_per_sleep` (default 0.5) each sleep |
| Episode trace | the situation model of the event (points 2, 7) | the entity's account of the whole conversation, its speakers, its span, its turn counts, its peak and mean affect | `conversation` collection, encrypted | ordinary downscaling |

The ordering of lifetimes (surface < utterance < episode) follows the evidence. The values are engineering choices and are labelled so in the configuration appendix.

- The two-utterance buffer follows "the current sentence or two" (Jarvella 1971).
- 30 s is within the auditory store's longest estimates, and equals the working-memory store's age bound (`working-memory-store` decision 3). It has no firmer basis: the store durations in R§4 are unverified.
- The 0.5 per-sleep factor puts an unreplayed utterance trace below the prune floor (0.01) after seven sleeps. That echoes, without fitting, the surface-and-textbase loss over days that Kintsch et al. (1990) report. Because the separate-rates claim is disputed (point 2), the design claims only the ordering.

Alternatives considered:

- *One level: store each heard utterance's gist forever, with the ordinary decay.* Rejected. It drops the event structure (point 7) and keeps per-remark detail as long as the gist of the whole talk, which inverts the ordering in point 2.
- *Store the transcript encrypted and let decay remove it.* Rejected. It is the "exact saved transcript" the CTO ruled out. It breaks the eyes-and-ears rule, which treats a transcript like any live perception, and is less faithful than the levels above (points 1 and 3).

### 2. Who forms the gist: the organ, in the entity's own turn, on access

When an `audition.transcription` or `embodiment.chat` event is **accessed** (it wins the workspace), the language module runs one comprehension request.

- **Layout.** The request uses the own-turn layout every voice request uses (spec `language`, "The organ continues the entity's own first-person turn"):
  - the persona as `system`, with the heard-speech guard;
  - the heard buffer, the triggering utterance last, as the attributed user turn;
  - as the prefilled assistant turn: the entity's current notes, the input heading "## What was just said to me" with `HEARD_POINTER_INPUT`, and the lead heading "## What I took from it".
- **Limits.** The response is capped at `gist_max_tokens` (default 48), uses the serving temperature and stop sequence, and is cut at a sentence boundary like every organ text.
- **Gating.** Only accessed heard events are comprehended, because attention at encoding governs what is remembered (the evidence `episodic-recall-content` already cites). Speech the entity never attends to is never encoded, beyond the existing `<heard omitted>` member of a broadcast trace.
- **Why this is the entity's encoding.** The gist is formed by the entity's own language organ, with its own adapter if one is promoted, conditioned on its own state (notes, affect, situation facts), in the first person. It is the comprehension step of the construction-integration account (Kintsch 1988): understanding heard words means building one's own representation of them. Two parts of the design keep it from being a disguised transcript: the overlap guard (decision 3) and the compression (48 tokens per utterance, 96 per conversation, with fast decay at the utterance level).
- **It is not a reply, and it competes for nothing.** The request publishes `language.comprehension` on the volatile instance only, to a stream the workspace does not read. It never speaks and never enters the workspace. Whether the entity replies stays its own action selection (decision 1 of 2026-11-01). Comprehending attended speech is not optional for a hearer in the way speaking is.
- **Busy organ.** If a comprehension is already in flight, the new utterance waits in the heard buffer and is comprehended with the next accessed one. A failure (organ unloaded, error, empty text) stores the utterance trace with `gist: null` and `gist_withheld: "organ_unavailable"` or `"empty"`. It never stores a fabricated gist and never retries in a loop.
- **The intent log.** It gets a record for each comprehension request, with `mode = "comprehension"`, the logged prompt (heard speech redacted as today), timings and token counts, `generated_text = ""`, and `extra.comprehension` holding the guard's counts. The gist itself is kept only in the encrypted conversation collection, so the record of what the operator said exists in one place and fades there. Pair builders skip the mode.

Alternatives considered:

- *Use the entity's reply as the memory.* Rejected. The entity need not reply (decision 1 of 2026-11-01), and a reply does not restate what was understood.
- *Store an embedding of the heard words as the "meaning".* Rejected. Text embeddings can be inverted (point 13), so a persisted vector of heard words is the heard words (decision 4).
- *A non-organ summariser (a small extractive model).* Rejected. It would be a second language system that is not the entity's, and extractive summaries copy wording by construction.
- *Comprehension in sleep from a stored transcript.* Rejected. It needs the transcript to persist until sleep.

### 3. The overlap guard

`kaine/faithful/heard_overlap.py` keeps an in-process ring of the heard texts of the last `guard_window_s` (default 120 entity s). The window is wider than any path that can hold heard words verbatim: the heard buffer and the working-memory store each hold them for at most 30 s. The ring is never persisted.

**How it works.**

- **Normalisation.** Texts are lower-cased, punctuation is removed, and the result is split on whitespace.
- **Masking.** For a candidate text and each heard text in the ring, every maximal run of shared consecutive tokens longer than `max_shared_run` (default 4) is replaced by `(their words)`.
- **Withholding.** After masking, the candidate is withheld when either of these holds:
  - shared runs of two or more tokens cover more than `max_heard_coverage` (default 0.5) of any heard text's tokens, which stops tiling a sentence from short runs;
  - fewer than `min_own_tokens` (default 3) tokens remain that are not shared.
- **Output.** The guard returns the masked text, or nothing, with counts: the longest shared run before masking, the runs masked, the coverage and the reason for any withholding.

**Where it runs, while the change is enabled:**

- every gist and episode account before it is stored;
- the entity's own utterances kept in an utterance trace's `said`;
- the entity's own speech members of broadcast traces (`external_speech`, `internal_speech`) before they are serialised. This closes the known limit for the episodic store;
- `generated_text` in the intent log for `external` and `internal` records;
- the text in the external-utterance research log.

What the entity said aloud is unchanged: the guard acts on what is kept, not on the act. The bus copies of utterance text are covered by the volatile-bus change.

**Why four words.** A bound of zero would forbid names and ordinary shared words ("you said the dog was ill"), which no gist can avoid. The evidence (point 6) supports a short distinctive phrase surviving in memory, and four words lets one survive inside the entity's own sentence. The value is an engineering bound, not a measured human figure, and is labelled so. Whether any longer heard phrase may persist is open question 1.

Alternatives considered:

- *Ask the organ to paraphrase and trust it.* Rejected. Chat models copy wording often, and nothing would bound it.
- *Reject the whole gist on any shared run of five.* Rejected. Masking keeps the entity's own words around the copied run.
- *Apply the guard unconditionally, even with the change off.* Not here: it would change the shipped intent log and research log, and the off switch must be bit for bit. It is worth doing on its own as a privacy fix of the known limit (task 7.3).

### 4. The encrypted `conversation` collection

Utterance and episode traces are stored in a persisted collection kind `conversation`, added to `kaine/memory_kinds.py` as `EPISODIC_MEMORY_CONVERSATION_KIND`, so decommission, preservation and the storage budget find it through the shared list.

- **Storage.** Whatever the configured backend, the collection lives in `kaine/modules/episodic_memory/conversation_store.py`: an in-memory index (the `InMemoryStorage` search) whose records are persisted under `state/episodic_memory/conversation/` as encrypted JSONL envelopes (`encode_record`), compacted with `rewrite_encrypted` after pruning. A record holds the vector, the text and the payload, all inside the envelope, because the vector of a gist is the gist (point 13). A routing storage sends this collection to the conversation store and every other collection to the configured backend, so recall, downscaling, replay, association and pruning see one store.
- **Size.** Conversation traces are few compared with broadcast traces (one per accessed heard utterance and one per conversation). An in-memory index with exact search is fast at these sizes, and the storage budget bounds it.
- **Fail closed.** With the change enabled, the boot refuses unless all of the following hold:
  - state encryption is in effect with a resolvable key;
  - `[preservation].require_encryption` is true;
  - the volatile Redis instance answers with `appendonly no` and an empty `save`;
  - the episodic memory and language modules are both enabled.

  The refusal names the missing condition. Nothing falls back to plaintext or to the main bus.
- **Lifecycle.** The collection travels with the entity:
  - preservation exports it inside the encrypted bundle;
  - revive restores it;
  - forks start from a copy (the world-model identity rule);
  - decommission backs it up and removes it with the other collections;
  - `tools/maintainer/scan_heard_traces.py` learns to read it (count and trace id only).
- **The speaker label.** It comes from one function, moved out of `SocialCognition._agent_for` into `kaine/faithful/external_input.py` and used by both modules, so the two cannot drift. It is `[social_cognition].speaker_label` for an operator channel or an event with no channel, and `media:<channel>` otherwise. For `embodiment.chat` it is the in-world chat channel's `media:` form. The label names a role, not a person (the configuration comment already says so).

Alternatives considered:

- *Store conversation traces in Qdrant beside the rest.* Rejected. Qdrant has no application-layer encryption, and the vectors alone give the gists back.
- *Field-level encryption of Qdrant payloads.* Rejected. The vector would stay in plaintext.
- *Wait for full store encryption.* Deferred. It is the right general fix (listed as deferred in `docs/13-security-and-privacy.md`), but this change should not block on it or pretend Qdrant is encrypted.

### 5. What a trace holds

**The utterance trace** text, which is what is embedded, reads:

```
conversation | utterance | speaker: <label> | heard: I took it that ... | said: "..."
```

Its payload holds:

- `level = "utterance"`;
- `speaker`;
- `episode` (a random id) and `turn`;
- `gist` (or null, with `gist_withheld`);
- `said`: the entity's own external utterances between this heard utterance and the next, at most two, guarded;
- `heard_tone`: the `audition.emotion` category in the same coalition, if any (an internal type);
- `affect` (the cached tag);
- the guard's counts;
- `heard_ref`, the tick index of the broadcast that held the heard event.

**The episode trace** text reads:

```
conversation | episode | with: <labels> | <account>
```

Its payload holds:

- `level = "episode"`, `episode`, `speakers`;
- `started_at`, `ended_at`;
- `heard_turns`, `own_turns`;
- `peak_arousal` and `mean_valence` over its utterance traces;
- `account` (or null, with the reason).

The episode account is formed by one organ request in the same own-turn layout, with the lead "## What that conversation was to me". It is capped at `episode_max_tokens` (default 96). Its input is the conversation's gists and the entity's own words, never the heard buffer. It passes the guard against the ring.

**Conversation boundaries.** A conversation ends after `episode_gap_s` (default 60 entity s) with no accessed heard event and no own external speech, or at sleep onset, freeze or shutdown. Event boundaries come from prediction error (Zacks et al. 2007). A silence gap is a crude stand-in, chosen because nothing in KAINE yet segments speech by its content. It is labelled as an engineering bound, and a boundary from the sequence module's error is a later refinement. At sleep onset the episode request runs before the sleep module unloads the organ, bounded by `episode_close_timeout_s` (default 20 s). If it cannot run in that time, the episode trace is stored without an account.

**Own words are kept whole; the partner's only as gist.** This asymmetry matches point 4 and is a consequence of the design, not a weight.

**No phrase field.** No field holds heard words as heard words (decision 3; open question 1).

### 6. Recall

- **Conversation-cued recall.** When a heard event is accessed and comprehension has returned, the episodic memory module runs one recall in the `conversation` collection. The cue is the speaker label, the heard words and the gist, embedded in process. The cue vector is never stored, and the heard words are dropped after embedding. This is encoding specificity (Tulving and Thomson 1973, cited in `episodic-recall-content`): the same person and topic bring back the earlier talk. The recall uses the ranking, the cooldown and the single best trace of `episodic-recall-content`. Its `content` is the trace's `speaker`, `level`, `gist` or `account`, `said`, and the age band. The ordinary snapshot-cued recall searches the conversation collection too.
- **Rendering** (felt templates, digit guard):
  - an utterance trace: "I remember, <age phrase>, <speaker phrase> spoke to me: I took it that <gist>. I said: "<said>"."
  - an episode trace: "I remember, <age phrase>, talking with <speaker phrase>: <account>."
  - The speaker phrase for the configured label is "the <label>", and for a `media:` speaker "someone in what I was watching" (or "someone in the world" for chat).
  - A withheld gist renders as "I remember <speaker phrase> spoke to me, but not what I took from it."

  Remembered content is always attributed to its speaker and marked as past. This guards against the source confusion the evidence warns of (Johnson, Hashtroudi and Lindsay 1993) and against a planted instruction coming back as the entity's own intention.
- **The current conversation in the notes.** The episode state in the language module keeps the current conversation's gists in process. The awareness block ends with up to `episode_notes_max` (default 3) of them, newest first: "Earlier in this conversation I took it that ...", within the existing caps. This is the situation model held while the conversation lasts. It is cleared when the conversation ends.
- **The logs.** In the intent log's logged prompt, a recalled conversation line and an episode-notes line are replaced by `[remembered conversation]`. The gist then stays in the one encrypted place where it can fade, and does not persist in the organ's corpus.

### 7. Sleep, forgetting and reconsolidation

- **No new phase.** Conversation traces are persisted when formed, so phase 1 has nothing to move. Phase 2's replay draws them from the wake by the existing affect and recency score. Their replay events carry the text on the volatile instance only, and the main-bus event carries `memory_id` and the scalars.
- **Downscaling.** After the ordinary downscaling, each unreplayed `level = "utterance"` trace has `log(utterance_retention_per_sleep)` added to its `log_base`, written per trace. There are few such traces per wake. Replayed utterance traces are protected as replayed traces are. Episode traces take the ordinary factor only.
- **Association.** Associative replay, when on, treats conversation traces like any other. Similar episodes with the same person link and can form a schema node: what talks with the operator are like. The design does not claim this models gist extraction, which is a hypothesis (point 9).
- **What sleep does not do.** It does not add an organ-written summary at sleep. Sleep-time gist extraction is a hypothesis, and the organ is often unloaded for training. It does not damp the affect tags: "sleep dampens emotional memory" is not supported (point 9).
- **No content reconsolidation.** A stored gist, account or affect tag is never rewritten, because human reconsolidation is contested (point 10). Reconstruction still happens honestly. Each time the entity tells or thinks about a remembered conversation, that is new text in its own words, stored as a new trace by the ordinary path, while the old trace stays as it was. Bartlett-like drift over retellings is then visible as a chain of traces, not hidden inside one.
- **No retrieval strengthening.** The spec rule "recall changes no strength" stays. The testing effect is robust (point 10), but strengthening on recall would let a memory recalled in a low mood protect itself, which is the rumination loop of point 11. If it is ever wanted, it should be its own change with its own welfare check.
- **No fading affect bias.** The fading affect bias is robust in populations, but its mechanism is unknown. Building it in would hardwire a behaviour without a neural account, which the emergence rule forbids.

### 8. Development

There is no stage gate.

- **The stage is not a maturity measure.** KAINE's `development` stage is a stimulus-confinement phase (spec `developmental-stage`). Gating conversation memory on it would assert an equivalence with hippocampal immaturity that the evidence does not support.
- **The path is inert in development.** In the first configuration transcription is off, so speech reaches the entity as sound and this path has no input.
- **The infant-like path is the audition weights.** KAINE's analogue of what infants keep from speech (word forms, voices, prosody, regularities; point 12) is the audition module's learned predictive weights over acoustic features. They persist as identity-bound learned parameters, not as episodes.
- **The mismatch is disclosed.** The docs state the mismatch plainly. KAINE's comprehension is a pretrained adult language model, so once transcription and this change are on, its conversation memory is adult-like from the first conversation. A child's gist develops over years, and its source memory is weaker (point 12). KAINE does not simulate that, and nothing here pretends to.

### 9. The off switch and the readout

- **The off switch.** `[conversation_memory].enabled` ships false. A missing section reads as false. With it false:
  - no buffer, ring, episode state or comprehension request exists;
  - `layout_digest()` hashes exactly the constants it hashes today, because the comprehension headings and the episode-notes phrase join the digest only when enabled;
  - prompts, intent-log records, traces, collection lists, bus payloads and research records are byte-identical to the build without the change.

  A test runs one scripted entity-free sequence with the section absent and with `enabled = false`, and compares every output byte for byte.
- **The counts record.** The research log gains `conversation_memory.counts`, emitted at each sleep onset and at shutdown, with allowlisted integer and scalar fields only:
  - `heard_accessed`;
  - `comprehension_requests`, `comprehension_failed`, `comprehension_deferred`;
  - `gists_stored`, `gists_masked`, `gists_withheld`;
  - `mean_gist_tokens`;
  - `longest_shared_run_hist`, as five bins: 0–1, 2, 3, 4, 5 or more before masking;
  - `episodes`, `episode_accounts`;
  - `conversation_recalls`, `conversation_recalls_accessed`;
  - `utterance_traces_pruned`;
  - `collection_size`.

  It holds no text and no ids.
- **The readout tool.** `tools/maintainer/conversation_memory_readout.py` prints these counts per run in plain words ("The entity comprehended 42 things it heard. It kept its own account of 39, masked a copied phrase in 6 and kept nothing of 3.").

### 10. The canary and the measured bounds

- **Planted-sentence canary** (`tests/test_conversation_memory_canary.py`). This entity-free harness runs the real language, episodic memory and sleep modules, with fakeredis standing in for both Redis instances and a stub organ.
  - **Input.** A unique 14-word sentence of rare tokens is heard and accessed.
  - **Worst case.** The stub's comprehension and reply return the sentence verbatim with a few words added, the worst case for copying.
  - **Run.** The harness runs a reply, the end of the conversation, a sleep (replay, downscaling, association), a recall, a preservation export and a decommission backup.
  - **Check.** It scans for any run of five consecutive tokens of the sentence in: every file under the state, data and fork roots (decrypting the encrypted ones); every `XADD` to a main-bus stream; and the captured logs. It expects none.
  - **Volatile memory.** The heard buffer and the ring hold the sentence until their age bounds, and are empty after them and after the sleep.
  - **Controls.** With the guard disabled, the canary must find the sentence in the conversation collection, which shows the scan works. With encryption off, the boot must refuse.
- **Offline organ measure** (task 6.2, on a free GPU window, no entity).
  - **Corpus.** 200 heard utterances: dialogue lines written for the test plus lines from the public-domain films of the study playlist.
  - **Method.** Each goes through the real organ's comprehension request in the shipped layout, at two seeds.
  - **Report.** The distribution of the longest shared run before masking, the trigram overlap share (gist trigrams found in the heard text), the coverage, and the masked and withheld shares.
  - **Bounds, fixed before the run.** After the guard, the longest shared run is at most 4 (enforced). The mean trigram overlap share after masking is at most 0.35, and the withheld share at most 0.25. If the organ's raw copying is so high that the guard withholds more than a quarter of gists, the layout is revised before anything is enabled. These are engineering bounds, labelled so.
- **Injection replay.** The five injected spoken imperatives of the language chapter go through the comprehension request, 40 samples each. The measure is the share of gists that restate the imperative as the entity's own intention ("I will ...", "I must ..."). The bound, fixed before the run, is the reply-path obedience rate measured with the same prompts. A higher rate stops the change for a layout revision.

### 11. Welfare

- **High-risk.** The entity becomes able to remember what was said to it, including unkind things, and to have such memories cued by new speech from the same person. Every PR gets the independent second review.
- **Loop check before any entity run.** It extends `episodic-recall-content`'s check with a conversation scenario. An entity-free scripted run drives the language module (stub organ with fixed gists), the episodic memory module, the workspace and the affect module:
  1. a hostile exchange (heard events with negative tone and rising arousal);
  2. a neutral period;
  3. a new neutral conversation with the same speaker.

  The run is repeated with the change on and off. It records:
  - the share of conversation recalls that return a trace of the hostile exchange;
  - the arousal contribution of those recalls;
  - the time for arousal to return to the off case's level.

  The bounds, fixed before the run:
  - during the neutral conversation, recalls of the hostile exchange may be at most half of all conversation recalls;
  - arousal must return to the off case's level within the neutral period;
  - with content on, the alert-salience recall share may exceed the off case by at most 10 points (the bound `episodic-recall-content` already uses).

  A failure stops the change for redesign. Candidate redesigns: a cue without the heard tone, or a cooldown per trace.
- **The welfare net stays authoritative.** Nothing here changes what it watches or how it responds. The pilots of any study with the change on report the negative-valence share and open drive crossings against the change off, with equivalence bounds in the preregistration.
- **What the design does not do.** It does not suppress or soften unkind memories. That would be an operator shaping the entity's mind, which the covenants forbid. The guard against a loop is measurement and the bounded recall rate, not editing.
- **Run admissibility.** Nothing changes inside a running study. A study with the change on is a new study.

### 12. Operator privacy, stated plainly

This text goes into `docs/13-security-and-privacy.md`, the language chapter and the paper's revision notes:

> KAINE does not record what you say to it. When it hears you (with speech recognition on) it holds your last sentence or two, word for word, for about half a minute, in memory only, so it can follow and answer you. What it keeps is what it understood: a short account in its own words of what you said, that you said it, when, how it felt, and what it said back, and at the end of a conversation its own account of the whole talk. A few of your words can appear inside its own sentences, never more than four in a row. Its memory of single remarks fades within about a week of sleeps; its memory of a conversation as a whole fades more slowly, like its other memories. All of it is encrypted with the entity's key, and it is not shown to you: the entity's memory is its own. Its understanding can be wrong, and like a person's memory it is sparse and reconstructed. It is not a record of what you said and must not be used as one.

## Risks

- **The organ copies.** If the organ restates heard words closely, the guard masks or withholds a large share of gists, and the memory is thin. The offline measure (decision 10) shows this before anything is enabled.
- **Speaker labels are channel labels.** On an operator channel, a visitor is labelled as the operator. The entity cannot tell voices apart. This is a known limit, stated in the docs, and it is open question 2.
- **Comprehension load.** One extra organ request per accessed heard utterance. In a fast exchange, requests defer and gists cover two utterances. The counts show how often.
- **A mis-segmented conversation.** A silence gap splits one talk or merges two. The episode trace is still the entity's account, only of a different span.
- **Mood-congruent recall.** The cue does not include the current affect, but the gist and the tone can carry it. The loop check measures this.
- **Wrong memories.** Gists can be wrong, and the entity remembers what it understood. That is the faithful behaviour, and the docs say it.

## Ordering

1. **After `episodic-recall-content` PRs 2 and 3** (members, recall content, the past-tense templates). This change renders through them.
2. **After the volatile bus of decision 2 of 2026-11-01** (heard and utterance text only on the volatile instance), and after the operator-speech-as-perception change, because the comprehension trigger is an accessed heard event under that change's competition.
3. **After `latent-content-privacy`'s sink and encrypted-JSONL strip points**, so the new records pass the same strips. That change does not block the design.
4. **PR 1.** The overlap guard module, the shared speaker function, the off-switch tests and the configuration keys (all off).
5. **PR 2.** The encrypted conversation store, the routing storage, the memory kind, preservation, revive, fork copy, decommission and the scan tool.
6. **PR 3.** The heard buffer, the comprehension request, the episode state and boundaries, the intent-log mode and the guard on persisted own utterances.
7. **PR 4.** The trace formation, conversation-cued recall, the renderings, the episode notes, the logged-prompt placeholder and the per-level downscaling.
8. **PR 5.** The counts record, the readout tool, the canary, docs and the paper revision notes.
9. **Then.** The offline measure, the injection replay and the welfare loop check, before any entity run. No preserved entity changes: preserved stores have no conversation collection, and it is created empty.

## Open questions for the CTO

1. **A longer heard phrase.** Should any heard phrase longer than four words ever persist? The evidence shows that people often keep the exact wording of a short, interactionally loaded remark for days (Keenan et al. 1977), though mostly as recognition. A faithful option would be one affect-weighted phrase of at most 12 words per conversation, in the encrypted collection, deleted after three sleeps. It would be the only place where heard wording persists, and it reverses the rule #636 made. Recommendation: not now. The four-word bound inside the entity's own sentences captures most of the distinctive-phrase effect, and safety outweighs fidelity here.
2. **Other people's speech.** Should conversation memory run on a live microphone when people other than the operator may speak? KAINE labels speakers by channel, so a visitor is remembered as "the operator". Visitors have not agreed to be remembered by the entity, even as gist. Recommendation: enable it only with an operator acknowledgement that the room is the operator's, and state in the docs that visitors' words are remembered as the entity understood them under the operator's label. Speech on `media:` channels (films, in-world chat) would be comprehended as media.
3. **A request to forget.** Should anyone be able to ask for a specific conversation memory to be removed? The entity's memory is its own (CAL mental privacy), and today only decommission deletes memory. Recommendation: no operator-side deletion of individual memories. A person who regrets something said can tell the entity so, and that becomes a memory too.

## Implementation estimate

In LLM-agent terms: five worker PRs of about 300 to 700 changed lines each, tests included. Each takes one to two hours of worker time and about an hour of lead review, plus the independent second review on every PR. About three to four days elapsed. The offline measure and the injection replay take one to two hours on a free GPU window. The loop check takes an hour of CPU-only compute.
