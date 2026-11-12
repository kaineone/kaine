## Why

KAINE's episodic memory module provisions four Qdrant collections (defined in `kaine/memory_kinds.py:29`): `short_term`, `episodic`, `semantic`, and `procedural`. The `semantic` collection exists, accepts writes, and is never written to by any code path.

The associative replay phase (sleep phase 3) already builds schema nodes: when a trace accumulates `n_sch` or more links (default 3; `kaine/modules/episodic_memory/associations.py:165`), the co-replay logic forms a centroid of the linked traces' embeddings and stores it in the `schemas` association kind. These centroids are geometric averages, not decontextualized knowledge. They capture what is similar across episodes but carry none of the abstraction that separates semantic memory from episodic memory in the literature.

Tulving (1972, 1985) distinguished episodic memory (context-bound events the individual re-experiences) from semantic memory (decontextualized facts and regularities). The CLS framework (McClelland, McNaughton, and O'Reilly 1995) gives the computational rationale: a fast, sparse hippocampal store and a slow, distributed neocortical store with different learning rates. Moscovitch et al. (2016) describe a transformation account in which repeated reactivation extracts gist into neocortical representations. The mechanism is graded: with enough repetition, the common elements of multiple episodes separate from their source contexts and become retrievable on their own.

KAINE's schema nodes are the seed. A schema node that persists across multiple sleeps, collecting more links and surviving strength pruning, is a statistical regularity that warrants extraction into the semantic store.

## What Changes

A semantic extraction step added to sleep phase 3, after schema node formation:

1. A schema node whose link count passes a configurable threshold (`semantic_extraction_threshold`, default 2 * `n_sch`) is extracted into the `semantic` collection. The vector is the node's centroid. The payload carries the common elements across the linked episodes: shared affect tags, shared source modules, shared content keywords, the originating node id, and the extraction timestamp.

2. The extracted node is marked (`extracted_to_semantic: true` in its `schemas`-collection payload) so subsequent sleeps skip it. If the node accumulates more links after extraction, a re-extraction updates the existing semantic point rather than creating a duplicate.

3. A `semantic_recall` path in `kaine/modules/episodic_memory/memory.py` searches the `semantic` collection alongside or after the `episodic` collection. Semantic matches produce an `episodic_memory.semantic_recall` event with a distinct payload shape (no source context, since semantic memory is context-free by definition).

4. The episodic recall's familiarity signal and the semantic recall's signal are reported separately. The language module can distinguish "I've experienced something like this before" (episodic familiarity) from "I know this" (semantic match).

## Impact

- Code: `associations.py` (extraction trigger), `memory.py` (semantic recall path), `storage.py` (write to `semantic` collection), `module.py` (event routing). Sleep `phases.py` calls the extraction after the existing schema-node formation.
- Licence: no new dependency. The semantic collection uses the same `all-MiniLM-L6-v2` embeddings as the episodic collection.
- Risk: LOW. The extraction runs during sleep, writes to an already-provisioned collection, and the recall path is additive (existing episodic recall is unchanged). The extraction threshold prevents premature generalization from few episodes.
