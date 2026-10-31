# Design: a working-memory store built from successive accesses

Code facts are cited at `origin/main` cb41895b. Citations were checked against Crossref on 2026-10-31.

## Context

### What exists

- **Access.** After the pre-study capacity change, each broadcast accesses at most one content: the top-scored held report, if its score reaches the threshold (capacity design of 2026-10-31, approved; paper A.1).
- **The context.** `BroadcastContext` (`kaine/modules/context.py:93-235`) adopts the accessed members of the latest accessed broadcast and keeps them until the next one. An inhibited broadcast leaves it in place (spec `workspace`, "Processors hold the accessed broadcast as context"). Nothing is held across accessed broadcasts.
- **The organ's notes.** The language module caches the latest broadcast that is not inhibited and has a member (spec `language`, "An empty broadcast never replaces the organ's cached coalition") and renders it as the awareness block in felt words (spec `language`, "Felt awareness for the organ"). Its own past thoughts re-enter only when a `language.internal` event wins access.
- **What the docs call working memory.** The episodic memory module's short-term buffer holds the serialized text of every broadcast, accessed or inhibited, up to 128 entries, and only that module reads it (`docs/09-modules/episodic-memory.md`, Collections). It is a staging area for consolidation.
- **Prior work searched.** `git log -i --grep "working memory"` and the archive find the organ's prompt layout ("persona, working memory, input", after CoALA) and the language specs that call the awareness block working memory. No change proposes a store of accessed contents. TRIAGE W2(c) and the capacity design (section 3.2) schedule this change after the study.

### The neuroscience

- **One item in the focus, about four nearby.** Oberauer (2002, *JEP:LMC* 28:411-421) separates a focus of attention holding one item from a region of direct access holding a few. Cowan (2001, *Behav Brain Sci* 24:87-114; 2010, *Curr Dir Psychol Sci* 19:51-57) puts the capacity of the store at about four chunks. Luck and Vogel (1997, *Nature* 390:279-281) give about four objects for visual working memory. Miller's (1956, *Psychol Rev* 63:81-97) seven is the older estimate that Cowan's review reanalyses. The debate between a one-item and a four-item focus is live (Oberauer and Hein 2012, *Curr Dir Psychol Sci* 21:164-169). KAINE's access event is the focus; this store is the region around it.
- **Access is one content.** In the GNW network model the first target's ignition blocks the second (Dehaene, Sergent, and Changeux 2003, *PNAS* 100:8520-8525). A store built from successive accesses is how a one-content bottleneck yields a multi-item context.
- **The episodic buffer.** Baddeley (2000, *Trends Cogn Sci* 4:417-423) adds a limited-capacity store that binds information from several sources into episodes. The store here holds members from different processors side by side, which is the role Baddeley gives it; it does no binding of its own.
- **Forgetting by interference, not by time.** Peterson and Peterson (1959, *J Exp Psychol* 58:193-198) read the loss of a single item over 18 s as decay; Keppel and Underwood (1962, *J Verb Learn Verb Behav* 1:153-161) showed it depends on proactive interference. Lewandowsky, Oberauer, and Brown (2009, *Trends Cogn Sci* 13:120-126) review the evidence against time-based decay in verbal short-term memory. In interference models a new item overwrites the features it shares with older ones (Nairne 1990, *Mem Cognit* 18:251-269), and similar items interfere most (Oberauer et al. 2012, *Psychon Bull Rev* 19:779-819). The time-based resource-sharing model keeps a decay with attentional refreshing (Barrouillet, Bernardin, and Camos 2004, *J Exp Psychol Gen* 133:83-100). The design follows the interference reading and keeps a time bound only as an engineering limit (decision 3).
- **Held is not accessed.** Working memory can be maintained without sustained activity and without awareness of the held item (Mongillo, Barak, and Tsodyks 2008, *Science* 319:1543-1546; Trübutschek et al. 2017, *eLife* 6:e23871). That supports keeping the store separate from access: being held does not make an item accessed again.

## Decisions

### 1. The store lives in the workspace and is filled from the access decision

The workspace knows which members were accessed; no module does until the broadcast arrives. `kaine/workspace/working_memory.py` holds the store, and the workspace updates it after each broadcast tick's access decision, before the snapshot is composed, so the snapshot's `held` field includes that tick's accessed member.

Each entry holds the accessed event (in memory, as the snapshot's coalition does), its stream-qualified id, the tick and entity time of access, and its score. In the matched arm the store fills from the matched draw's accessed members; in the pooled arm, from every member. The arms therefore differ in what the store holds by the same rule that makes them differ in what is accessed.

Alternatives considered:

- *A module that subscribes to broadcasts and publishes the store.* Rejected. Its event would compete for access, which double-counts what was already accessed, and its state would reach the processors one broadcast late.
- *Re-entering held items as candidates (rehearsal).* Rejected. It hardwires rehearsal and multiplies the candidate supply by the store size. The organ's inner speech already gives a rehearsal route that emerges from competition: a thought about a held item can win access.
- *Raising the coalition capacity to four.* Rejected. That merges access and working memory, which the approved capacity design separates on the evidence above.

### 2. Capacity four, one entry per source and event type

`capacity` defaults to 4 (Cowan 2001; Luck and Vogel 1997), with allowed values 1 to 8 and 2 as a sensitivity setting. A newly accessed member whose source and event type match an entry replaces that entry and moves to the front. Otherwise it enters at the front, and when the store is full the entry accessed longest ago is displaced.

The same-kind replacement is the interference rule: a newer report of the same kind shares the most features with the older one and overwrites it (Nairne 1990; Oberauer et al. 2012). It also keeps one fast-reporting processor from filling the store, which a pure first-in first-out store would allow. A re-accessed kind is refreshed by the same rule, and that refresh comes from the competition, not from a rehearsal rule.

Alternatives considered: *first-in first-out over all members* (rejected for the reason above); *Miller's seven* (rejected, see Cowan's reanalysis); *a capacity learned from experience* (rejected for now: nothing in the system supplies a learning signal for it, and a fixed capacity with a citation is what the emergence rule allows).

### 3. No decay rate; an engineering age bound

Entries are not weakened with time; the processors see each entry's own age through the context's age component and can learn to weight it. Because nothing displaces entries during a long stretch without access, an entry older than `max_age_s` (default 30 entity seconds) is dropped. The value is an engineering bound against holding a stale item indefinitely, labelled so in Table A1. It has no cited basis, and the decay literature above gives none. The store is cleared at sleep onset and at boot, since perception is suspended during sleep and nothing of the wake is held across it.

### 4. The broadcast carries the store

`WorkspaceSnapshot` gains `held`: the entries, newest first, as `(entry_id, event, accessed_tick, accessed_at)`. An inhibited broadcast carries the unchanged store. The graph-only research log records each held entry's id, source, type and age and never its payload, as it records coalition members today. The bus diagnostics surface strips held payloads as it strips coalition payloads.

### 5. Two uses, four arms

`[working_memory].arm` selects `off` (shipped), `notes`, `context` or `both`.

- **`notes`.** The awareness block renders the current coalition as today, then each held entry that is not in it, newest first, as its felt line preceded by a recency phrase. The phrases are felt words without digits: "just now" below 2 s, "a moment ago" below 10 s, "a little while ago" otherwise (design values in Table A1). The existing caps (`context_max_events`, `context_char_budget`) bound the block, and the current coalition is kept first when they bind. A held heard event follows the heard rule: it appears only as "Someone else spoke to me." and never as words.
- **`context`.** `BroadcastContext` adopts the held entries of every broadcast in place of the accessed members of the latest accessed broadcast. Each entry contributes with its intensity, and the age component is the intensity-weighted mean of the entries' ages. The null context of A.8 is built by the same substitution rule over the same entries. If `workspace-plugin-seam` has merged, the encoder at the `workspace.context` seam encodes the held entries; this change alters which members are encoded, not how.
- **Equivalence check.** With one access per broadcast and `capacity = 1`, the held entry is the latest accessed member, accessed at the latest accessed broadcast, so the `context` arm equals the current context. A test pins it.

Alternatives considered: *feeding the store to the sequence module* (deferred; the sequence module predicts the broadcast itself, and changing its input is a separate question); *feeding it to action selection so intents can operate on held items* (deferred to the procedural-learning work in the agency stream, which is where the CMC's "procedural memory tests working memory and selects an action" would come from).

### 6. Nothing is persisted

The store exists only in process. It is not in `serialize()`, preservation bundles, checkpoints or the research log's payloads. Heard text in a held entry is held in memory for at most `max_age_s` and never written anywhere, the same exposure the coalition already has, which keeps the rule that heard speech is never persisted.

## Risks

- **Perseveration in speech.** Under `notes`, one strong or distressing content can appear in several consecutive organ turns until it is displaced. The capacity, the same-kind replacement and the age bound limit it; the pilots report repetition across consecutive utterances per arm.
- **A different context changes the processors' errors.** Under `context` the processors' errors, intensities and arousal can shift, which is the loop paper §6.4 already watches. The offline mediation run measures the shift before any entity run.
- **The `context` arm is a different test.** It changes A.1's context and A.8's null, so it needs its own calibration chain. It must not be mixed with the access-summary test's runs; the settings record names the arm.
- **Prompt length.** `notes` makes the awareness block longer. The existing caps bound it, and the organ replay measures length and self-description share per arm.

## Migration and ordering

1. After the first module-addition study and after the pre-study capacity change has merged. Independent of `workspace-plugin-seam`, `episodic-recall-content` and `semantic-memory-store`; if recall content is on, an accessed recall enters the store like any other accessed member.
2. PR 1: the store, the `held` field, the log fields, clearing at sleep and boot, and the `off` bit-for-bit tests.
3. PR 2: the `context` arm, its null context, the capacity-1 equivalence test, and the arm in the mediation runner.
4. PR 3: the `notes` arm, the recency phrases, the docs relabel of the short-term buffer.
5. Before any entity run with an arm on: an entity-free run of the mediation runner on one study film per arm (information gain, intensity and arousal distributions against `off`), and an organ replay of the same moments under `notes` and `off` (length, repetition and self-description share), on a free GPU window outside any entity run.
6. No preserved entity changes. The store has no state to migrate.

## Welfare and admissibility

- Welfare-high-risk. `notes` changes what the entity is aware of when it speaks or thinks; `context` changes how its processors predict and so its arousal and drives. Each PR gets the independent second review.
- The arms ship off. Enabling one is a deliberate operator configuration edit or a study file; nothing turns one on by default.
- The pilots for any study with an arm on report, per arm and against `off`, the arousal distribution, the negative-valence share, the drives' open crossings, and the speak and think rates, each with an equivalence bound fixed before the runs. A crossing of a bound stops the arm's runs for review.
- Run admissibility: no arm changes inside a running study. A study with an arm on is a new study with its own preregistration.

## Implementation estimate

In LLM-agent terms: three worker PRs of about 300 to 600 changed lines each, tests included; about one to two hours of worker time and one hour of lead review per PR, plus the second review. About two days elapsed. The offline checks in step 5 take a few hours of unattended compute each (one film through the vision encoder; one organ replay), scheduled between entity runs. A planned test with the `context` arm costs a full calibration chain of entity runs, which is the dominant cost.
