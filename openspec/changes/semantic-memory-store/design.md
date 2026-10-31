# Design: a semantic store abstracted from episodes in sleep

Code facts are cited at `origin/main` cb41895b. Citations were checked against Crossref on 2026-10-31.

## Context

### What exists

- **The collection.** `semantic` is one of the four canonical collection kinds (`kaine/memory_kinds.py:28-34`), created at initialize (spec `episodic-memory`, "Four CLS-separated collections"), included in the module's collection set (`kaine/modules/episodic_memory/memory.py:71`) and in decommission's backup and deletion (`kaine/lifecycle/decommission.py:268`). It is empty.
- **Associative replay** (paper A.10; specs `episodic-memory` and `hypnos-consolidation`, "Phase-3 associative replay links related traces"). After phase 2's downscaling, phase 3 co-replays up to `n_pair` pairs of a replayed trace and an older trace from an earlier wake with cosine similarity in `[sim_min, sim_dup)`, sets their link weight, caps each trace at `n_link` links, and gives a trace with at least `n_sch` links a schema node: the centroid of its and its partners' embeddings, with strength the mean link weight. A node is removed when its trace falls below `n_sch` links or is deleted. Recall ranks nodes with traces and returns a node with its center trace's text. Associative replay ships off.
- **Members.** After `episodic-recall-content`, each new trace stores its coalition's members with the felt fields of each, and heard members without words.
- **Prior work searched.** `git log -i --grep "semantic memory\|semantic store"` finds nothing beyond the reserved collection. `mnemos-retrieval-energy` mentions HippoRAG 2 for semantic memory as a later option, not proposed; its default embedder's licence is non-commercial, as that design notes. No archived change fills the collection.

### The neuroscience

- **Semantic memory is knowledge without its episode.** Tulving (1985, *Can Psychol* 26:1-12; 2002, *Annu Rev Psychol* 53:1-25) separates knowing facts from re-experiencing events. Renoult et al. (2019, *Trends Cogn Sci* 23:1041-1057) review evidence that the two lie on a continuum and that semantic knowledge forms from episodes as their particulars are lost.
- **It is extracted slowly, by interleaving.** Complementary learning systems theory has a fast hippocampal store and a slow neocortical learner that extracts structure from many replayed episodes, slowly so that new learning does not overwrite old (McClelland, McNaughton, and O'Reilly 1995, *Psychol Rev* 102:419-457; Kumaran, Hassabis, and McClelland 2016, *Trends Cogn Sci* 20:512-534).
- **Consolidation transforms episodes into gist.** In trace-transformation theory, memories lose contextual detail over consolidation and become schematic (Winocur and Moscovitch 2011, *J Int Neuropsychol Soc* 17:766-780). Sleep favours generalization over detail (Stickgold and Walker 2013, *Nat Neurosci* 16:139-145), and overlapping replay of related memories builds schemata (Lewis and Durrant 2011, *Trends Cogn Sci* 15:343-351). Schemas are structures abstracted across experiences that speed later learning (Tse et al. 2007, *Science* 316:76-82; Gilboa and Marlatte 2017, *Trends Cogn Sci* 21:618-631).
- **The cost of gist.** Sleep's gist extraction also produces false memories of items that fit the gist but were never seen (Payne et al. 2009, *Neurobiol Learn Mem* 92:327-334). A store that generalizes across moments will sometimes generalize across moments that were alike only on the surface.
- **Semantic knowledge is cross-modal.** In the hub-and-spoke account, concepts combine modality-specific features through a transmodal hub (Lambon Ralph et al. 2017, *Nat Rev Neurosci* 18:42-55; Binder and Desai 2011, *Trends Cogn Sci* 15:527-536). A gist that records which kinds of report recur together is a small instance of that combination.

## Decisions

### 1. Promote schema nodes that span several wakes

Phase 3, when `[episodic_memory.semantic].enabled` and associative replay are both on, calls `promote_semantic()` after `associate()` and before `prune()`. For each schema node formed or changed in that sleep, it takes the node's member traces (center and partners). If they span at least `min_wakes` distinct `born_sleep` values (default 3), the node is promoted.

The wake count is the criterion because semantic knowledge is what recurs across separate episodes (Renoult et al. 2019); a node whose traces all come from one wake is one repeated episode. The schema node is the source because it is the existing product of overlapping replay, the mechanism the paper already cites (Lewis and Durrant 2011), so promotion adds abstraction to a structure sleep already builds.

Alternatives considered:

- *Use schema nodes as the semantic store as they are.* Rejected. A node holds no abstracted content, follows one trace's links, and disappears when they change; recall of a node returns an episode's text.
- *Cluster all traces offline (for example k-means) and call the clusters concepts.* Rejected. It is unrelated to replay, which is the consolidation route the cited accounts describe, and its cluster count would be a hand-set parameter.
- *Extract facts from traces with a language model or a retrieval graph (HippoRAG 2 style).* Rejected. It imports pretrained semantics into the entity's memory, which the emergence rule excludes, invites invented facts, and the reference system's embedder is non-commercially licensed.
- *Train the world model on replayed traces (the CLS slow learner) instead.* Not a substitute. That is a learner, not a declarative store, and its input is the broadcast summary. It is a separate follow-up, not specified here.
- *Store word meanings from heard speech.* Out of scope: speech recognition is off in studies, heard speech is never persisted, and grounding is its own workstream.

### 2. The gist

From the accessed members of the node's member traces, `semantic.py` computes:

- `kinds`: each (source, type) present in at least `min_share` of the member traces (default 0.5), with its `share` and, for each felt field of that type with numeric values, the median;
- `affect`: the mean of the member traces' affect tags (intensity, valence, dominance);
- `own_words_share`: the share of member traces that held an accessed thought or utterance of the entity's own;
- `n_episodes`, `n_wakes`, `first_sleep`, `last_sleep`;
- `members`: the member trace references, at most `max_members` (default 64), most recent kept;
- the vector: the centroid of the member traces' embeddings, under the store's embedding-space stamp.

It holds no trace text, tick, wall-clock time or single episode's entity time, and none of the entity's own words. Words are left out because aggregating them would need a text model to say what they have in common, which is the pretrained semantics rejected above; the share records that the entity often spoke or thought in such moments.

Medians are used because the felt fields are bounded readings with skewed distributions, and the median of a few episodes does not follow one outlier.

### 3. Slow update and merging

A promoted node whose centroid has cosine similarity of at least `sim_merge` (default 0.9) with an existing entry, or that shares at least half its member traces with one, updates that entry: the gist is recomputed over the union of members (bounded by `max_members`), and `n_episodes`, `n_wakes` and `last_sleep` grow. Otherwise a new entry is created. Because each update recomputes over all bounded members, a new node of a few traces moves an entry of many only a little, which is the slow, interleaved learning the complementary-learning-systems account requires.

### 4. Strength, downscaling and pruning

An entry is stored at strength 1 on the module's log gain, as a trace is, and is protected in the sleep that promoted or updated it. Every other sleep downscales it by the factor that scales an unreplayed trace, and the floor and the storage budget prune it as they prune traces. Knowledge that stops recurring fades; knowledge that keeps being re-promoted stays. A separate, slower decay for semantic entries was considered and rejected: there is no cited value for it, and re-promotion already gives recurring knowledge a longer life.

### 5. Retrieval and rendering

The live recall searches the semantic collection with the others; ranking stays strength times similarity. When a semantic entry ranks best and `recall_content` is on, `content` carries `kind = "semantic"`, the kinds with their share and medians, the affect centroid, `own_words_share`, and the entry reference. The intensity rule uses the entry's affect intensity as it uses a trace's.

The felt line frames the content as knowledge: "I know this kind of moment:" followed by each kind's line in the habitual present with a frequency word from its share ("often" at least one half, "usually" at least 0.7, "almost always" at least 0.9), and a line for the affect centroid in the same form ("and I usually feel calm"). An own-words share of at least one half adds "and I often have something to say". No digit appears. The frame keeps knowledge apart from both perception and recollection (Johnson, Hashtroudi, and Lindsay 1993, *Psychol Bull* 114:3-28).

### 6. Lifecycle and identity

Semantic entries are the entity's memory. They are encrypted at rest with the stores, exported in preservation bundles, restored on revive, copied with memory when a fork copies its parent's memory, and backed up and deleted by decommission with the other collections. They are never merged between entities. The change adds tests for each path rather than new lifecycle code, since the collection is already a canonical kind.

## Risks

- **False generalization.** A gist may join moments that were alike only in how their traces read to the embedder (Payne et al. 2009 is the human analogue). The offline check (task 6.1) measures how often promoted entries' member traces share a film item or own-speech content.
- **Little to abstract.** With today's members (graded readings and own words), entries describe which reports recur together and how strongly; they say nothing about objects or scenes. That is the honest extent of what the store can know from what KAINE keeps, and the paper text must say so.
- **Dependence on associative replay.** Associative replay ships off and has its own open questions (paper §9, the memory rules bullet). With it off there is no semantic store.

## Migration and ordering

1. After the first module-addition study and after `episodic-recall-content` has merged (members are the gist's input). Independent of `workspace-plugin-seam` and `working-memory-store`.
2. PR 1: `semantic.py` (promotion criterion, gist, merge), storage on the log gain, the phase-3 hook.
3. PR 2: recall over the semantic collection, the `content` form, the felt rendering.
4. PR 3: lifecycle tests, research-log counts, docs, paper notes.
5. Existing stores have no semantic entries. Traces without members contribute to a node but not to a gist; a node whose member traces have no members is not promoted.

## Welfare and admissibility

- Welfare-high-risk. The entity gains standing expectations about its own experience. A gist over distressing moments ("I usually feel tense") is the analogue of a negative schema and could colour later appraisal through the recall route. Each PR gets the independent second review.
- `enabled` ships false; it needs associative replay and recall content, both off by default. Enabling is a deliberate operator configuration edit or a study file.
- **Check before any entity run.** An entity-free run of the module and the sleep phases over a scripted multi-wake history with a planted recurring pattern (one kind of report with a high reading, across four wakes) and a non-recurring control. Pass: the pattern is promoted with the right kinds and the control is not. The same run, with a negative affect tag planted on half the pattern's episodes, records the share of semantic recalls with a negative affect centroid; the bound, fixed before the run, is that it does not exceed the negative share of the underlying episodes by more than 10 points.
- **In the pilots** of any study with the store on: per run, the number of entries, the share with a negative affect centroid, the share of recalls that were semantic, and the welfare observer's negative-valence share against the store off, with equivalence bounds in the preregistration.
- Run admissibility: nothing changes inside a running study.

## Implementation estimate

In LLM-agent terms: three worker PRs of about 300 to 600 changed lines each, tests included; one to two hours of worker time and about an hour of lead review per PR, plus the second review. About two days elapsed. The checks before an entity run take under an hour of CPU with no entity and no GPU. The real cost is that the store fills only over many wakes, so evaluating it in an entity takes the length of a study branch, not hours.
