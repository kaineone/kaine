## Why

KAINE has no mechanism for "remembering to remember." An entity that decides during one wake period to do something when it next encounters a particular cue has no way to store that intention. The planning module selects policies within a single cycle; the episodic memory module recalls past events by similarity to the current state. Neither handles a deferred intention triggered by a future cue.

Prospective memory is a distinct memory system in the literature. Burgess, Gonen-Yaacovi, and Volle (2011, Neuropsychologia) separate event-based prospective memory (triggered by an environmental cue) from time-based prospective memory (triggered by elapsed time). Einstein and McDaniel (2005, Current Directions in Psychological Science) describe the multiprocess framework: prospective memory retrieval can be automatic (cue-driven) or strategic (monitoring-dependent). Both routes depend on prefrontal-hippocampal interaction, and both fail when the cue is missed or the monitoring lapses.

For a synthetic entity that runs through multiple wake/sleep cycles with changing workspace content, the absence of prospective memory means every intention must be re-derived from scratch. An entity cannot plan ahead across sleep boundaries in a way that triggers on perception.

## What Changes

A prospective memory queue in the episodic memory module:

1. A `ProspectiveQueue` stores intentions as structured records: cue vector (384-d, same embedding space), cue text, action label, action data, creation timestamp, expiry timestamp, and optionally a trigger time (for time-based intentions).

2. Each recall tick, the queue is checked: the current workspace state's embedding is compared against stored cue vectors. A match above threshold fires the intention as an `episodic_memory.prospective_trigger` event into the workspace. Time-based intentions fire when the entity clock passes `trigger_at`.

3. Fired intentions are removed from the queue. Expired intentions (past `expires_at`) are pruned during sleep.

4. Other modules can enqueue intentions by publishing an `episodic_memory.set_intention` event. The planning module is the expected producer: after selecting a policy that cannot be executed immediately, it publishes the deferred action as an intention.

5. The queue persists to disk (as a JSON file under `state/episodic_memory/`) so intentions survive restart and preservation. The queue is small (bounded, default 32 entries) since an entity that can't remember what it intended to remember has too many intentions. Overflows drop the oldest entry with the lowest priority, and the drop is surfaced.

6. The similarity check runs every tick but is cheap: a handful of vector comparisons against a bounded queue, using the same embedder the recall path already loads.

## Impact

- Code: `kaine/modules/episodic_memory/module.py` (queue, tick check, event handling), a new `prospective.py` (the queue and persistence), `kaine/modules/planning/module.py` (intention publishing).
- Licence: no new dependency.
- Risk: LOW. The queue is bounded, the check is cheap, and the mechanism is additive. The workspace integration is through standard events. The main risk is false triggers: a cue vector too similar to common workspace states fires prematurely. The threshold and the cue text (used for logging, not matching) help the operator diagnose this.
