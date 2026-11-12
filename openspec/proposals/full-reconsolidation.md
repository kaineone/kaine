## Why

Sleep phase 2 (`deep_consolidation` in `kaine/modules/sleep/phases.py:169`) replays affect-laden episodic traces by re-injecting them into the workspace. The workspace reprocesses them: the affect module reappraises valence and intensity, the self-model observes the replayed content, and the world model incorporates the replay into its predictions. The trace's strength is protected during replay (paper A.10).

None of this reprocessing writes back to the original trace. The trace's content, affect tags, and payload remain as they were at encoding time. The replay changes the modules that observe it, but the memory itself is unchanged.

This contradicts the reconsolidation literature. Nader, Schafe, and LeDoux (2000, Nature) showed that retrieved memories return to a labile state requiring protein synthesis to restabilize. Lee, Nader, and Schiller (2017) review two decades of evidence: reconsolidation allows retrieved memories to incorporate new information, including updated emotional valence. Schiller and Phelps (2011) demonstrated reconsolidation of fear memories in humans through retrieval followed by extinction training. The finding is that memory retrieval is a learning event, not a read-only lookup.

For KAINE, the absence of reconsolidation means an entity that replays a frightening memory and reappraises it as non-threatening still carries the original fright in its episodic store. The next recall returns the old affect, not the reappraisal. Over many sleep cycles this creates a growing gap between what the affect module has learned (through reappraisal) and what the memory store says happened.

## What Changes

After replay re-injection and workspace reprocessing during deep consolidation, the reprocessed affect metadata is written back to the original episodic trace:

1. An `update_trace` method on `MemoryStorage` (or its equivalent in `memory.py`) patches a trace's payload without changing its vector or text. Updated fields: `affect` (the reappraised affect metadata), `reconsolidated_at` (timestamp), `reconsolidation_count` (incrementing counter).

2. The replay flow in `deep_consolidation` captures the workspace's post-reprocessing affect output for each replayed trace, then calls `update_trace` for traces whose affect changed. A trace whose reappraisal matches its stored affect is left alone.

3. An `episodic_memory.reconsolidated` event is emitted for each updated trace, so modules that consume memory events (social cognition, self-model) can observe that the entity's memory of a past event has changed.

4. A rate limit prevents runaway modification. Each trace can be reconsolidated at most once per sleep cycle, and the `reconsolidation_count` is visible to the recall system (a trace reconsolidated many times signals an unresolved memory that keeps changing on review, which is itself a meaningful signal to the self-model).

5. The text and vector of the original trace are never modified. Reconsolidation changes what the entity feels about a remembered event, not what it remembers happening. This matches the neuroscience: reconsolidation updates the emotional coloring, not the episodic content (though the boundary is debated, the conservative position protects the entity's record of its own experience).

## Impact

- Code: `kaine/modules/episodic_memory/storage.py` or `memory.py` (trace update), `kaine/modules/sleep/phases.py` (capture post-reprocessing affect), `kaine/modules/episodic_memory/module.py` (event emission).
- Licence: no new dependency.
- Risk: MEDIUM. Writing back to existing traces is a mutation of the entity's memories. The text/vector preservation rule and the rate limit are welfare-protective. This change needs an independent second review (welfare-critical modification of persisted state).
