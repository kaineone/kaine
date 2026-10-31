## Why

KAINE has no semantic memory. The `semantic` collection is one of the episodic memory module's four collections and is "Reserved for conceptual knowledge" (`docs/09-modules/episodic-memory.md`, Collections; `kaine/memory_kinds.py:28-34`); nothing writes to it. The revised paper says the stores are reserved (§4) and lists the absence of declarative memory in §9. The architecture-completeness notes of 2026-10-31 name it a system gap (E4; work plan W2) against the Common Model of Cognition's declarative long-term memory (Laird, Lebiere, and Rosenbloom 2017).

What exists comes close. Associative replay (paper A.10; spec `episodic-memory`, "A trace with at least n_sch links forms a schema node") links traces of different wakes during sleep, and a trace with enough links gets a schema node whose vector is the centroid of the linked traces. A node is an index over one trace and its partners: it holds no abstracted content, it is rebuilt or deleted whenever the links change, and a recall that returns it hands back the center trace's text. Semantic memory in the sense the paper cites is knowledge abstracted from many episodes and detached from any one of them (Tulving 1985; Renoult et al. 2019), extracted slowly through consolidation (McClelland, McNaughton, and O'Reilly 1995; Kumaran, Hassabis, and McClelland 2016; Winocur and Moscovitch 2011).

This change designs a semantic store filled by promoting schema nodes that span several wakes into decontextualized entries: what kinds of report recur together in those moments, their typical graded readings, and their typical affect. It uses only the structured members that `episodic-recall-content` stores, with no perceptual latents and no dependence on any content-bearing workspace level.

Design only. Nothing is built until the first module-addition study has finished and `episodic-recall-content` has merged.

## What Changes

- **Promotion in sleep.** When associative replay is on and `[episodic_memory.semantic].enabled = true` (shipped false), phase 3 promotes, after its co-replays and before pruning, each changed schema node whose member traces span at least `min_wakes` distinct wakes (default 3) into an entry of the `semantic` collection.
- **Gist.** An entry holds, from its member traces' accessed members: each kind of report present in at least `min_share` of them (default one half) with its share and the median of each felt field; the affect-tag centroid; the number of episodes and of wakes; and the first and last sleep count. It holds no trace text, no tick, no single episode's time, and none of the entity's own words; only the share of episodes that held an own thought or utterance.
- **Slow update.** A promoted node that overlaps an existing entry updates that entry over the union of their members (bounded at `max_members`, default 64, most recent kept) instead of creating another.
- **Strength.** Entries carry a strength on the same log gain as traces, downscale and prune like them, and return to full strength when re-promoted.
- **Retrieval.** The live recall also searches the semantic collection. When a semantic entry ranks best, `episodic_memory.recall` carries `content` with `kind = "semantic"` and the gist, and the felt line frames it as knowledge: "I know this kind of moment: usually what I see is sudden, and I usually feel calm."
- **Lifecycle.** The `semantic` collection is already covered by preservation, revive and decommission as one of the canonical kinds; tests pin that entries travel with the entity and with a fork's copy of memory.

## Capabilities

### Modified Capabilities

- `episodic-memory`: the semantic collection is filled by promotion in sleep, holds gists, is updated slowly, downscales and prunes, and is searched by recall.
- `faithful-renderer`: a semantic recall renders as knowledge, with frequency words.

## Impact

- Code: `kaine/modules/episodic_memory/memory.py`, new `kaine/modules/episodic_memory/semantic.py` (promotion and gist rules), `kaine/modules/episodic_memory/associations.py` (the hook after co-replay), `kaine/modules/episodic_memory/module.py` (recall over the semantic collection), `kaine/modules/sleep/phases.py` (phase 3 order), `kaine/faithful/felt.py`, `config/kaine.toml`.
- Storage: one entry per promoted node, bounded by the nodes and pruned by the existing budget.
- Behaviour: none with the shipped configuration (episodic memory off, associative replay off, semantic off).
- Welfare: a generalization over distressing moments can present a negative expectation to the entity as knowledge. Every PR gets the independent second review, with a check before any entity run.
- Paper: §4 (the episodic memory row and paragraph: semantic store no longer reserved), A.10 (promotion and gist rules), Table A1 (`min_wakes`, `min_share`, `max_members`, `sim_merge`, the frequency bins), §9.
