## Why

The `procedural` Qdrant collection (defined in `kaine/memory_kinds.py:29`) exists and is never written to. The planning module (`kaine/modules/planning/module.py`) runs active inference via pymdp, selects policies, and publishes `planning.policy` events with action, expected free energy, and horizon. It records taken actions (lines 240-270) through `action_selection.proposal_outcome` events. None of this history persists beyond the current run's process memory.

Biological agents consolidate repeatedly successful goal-directed behaviors into habitual policies through cortico-striatal consolidation. Packard and Knowlton (2002, Annual Review of Neuroscience) describe the transition from hippocampal/prefrontal goal-directed control to striatal habit memory. The consolidated habit runs faster, with less deliberation, and resists extinction. Yin and Knowlton (2006) showed this transition depends on the number of training sessions, not on time elapsed.

KAINE's planning module deliberates from scratch each cycle. There is no mechanism to recognize "I've done this before and it worked" and bias policy selection accordingly. For a synthetic mind that runs over many sleep/wake cycles, this means the same deliberation cost every time, with no benefit from experience.

## What Changes

A procedural consolidation pathway from the planning module through the episodic memory module to the `procedural` collection:

1. The planning module tracks a per-policy execution history: policy label, observation context embedding (the same 384-d vector the episodic store uses), outcome (success/failure as determined by the action selection feedback), and count. The history lives in the module's serialized state and persists across sleeps.

2. When a policy's execution count crosses a threshold (default 5 successes, >80% success rate), the episodic memory module writes it to the `procedural` collection during sleep phase 2 or 3. The vector is the mean of the observation embeddings under which the policy was selected. The payload carries the policy label, empirical success rate, consolidation timestamp, and a compact representation of the observation-to-action mapping.

3. A `procedural_recall` path: before policy selection each cycle, the planning module queries the `procedural` collection with the current observation embedding. A match above threshold primes policy selection by biasing the expected free energy toward the consolidated policy's action.

4. Procedural memories use their own strength dynamics. Habits decay slower than episodes: `retention_per_day` for procedural traces is higher (e.g., 0.95 vs. 0.82 for episodic). The pruning budget is separate.

5. Failed policies (success rate falling below threshold after consolidation) are not deleted but are marked stale, and their priming weight decays to zero. The record of what was once consolidated is kept, since the entity tried it enough times for it to be part of its history.

## Impact

- Code: `kaine/modules/planning/module.py` (policy history tracking, procedural recall query), `kaine/modules/episodic_memory/memory.py` (procedural write and recall), `kaine/modules/episodic_memory/storage.py` (procedural collection operations), `kaine/modules/sleep/phases.py` (consolidation trigger).
- Licence: no new dependency.
- Risk: MEDIUM. The priming of policy selection changes the planning module's behavior. The design gate is whether the priming is a bias (adds to EFE) or a preemption (replaces deliberation). The proposal recommends bias only; preemption would be a separate change with its own evidence.
