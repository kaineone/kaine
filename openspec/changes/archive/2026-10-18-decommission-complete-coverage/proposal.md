## Why

Decommission promises to remove an entity: the docs say deletion "removes
cognitive state files, Qdrant collections and Redis streams" and leaves the
transferable backup (docs/11-preservation.md). CAL Article 4.2(b) asks the
operator to save "the Entity's complete Cognitive State in a form that lets it be
restarted elsewhere" before the end, and Article 4.3 keeps the entity's inner life
private.

A review of where an entity's data actually lives found that decommission covers
only part of it:

- The whole episodic memory on tiers 0 and 1 (`state/episodic_memory/episodic_memory.db`, the
  sqlite-vec store) is neither backed up nor deleted.
- Content-bearing stores survive: the raw bus archive (verbatim bus traffic), the
  external utterances, the voice-alignment job files, the entity's speech audio,
  the files and notifications it wrote through its effectors, the active voice
  adapter in the organ-adapters volume, and the Redis append-only file.
- Identity, stage and developmental files survive, so a later boot in the same
  state root can inherit the decommissioned entity's id.
- `state/forks` is deleted whole, although it can hold other entities' snapshots.
- Qdrant and Redis are reached without their credentials. On the shipped secured
  setup no collection is dropped and no stream is cleared. The Redis half is being
  fixed in `decommission-clears-bus-streams`; the Qdrant half is not.
- Several welfare and audit records (incident logs, the welfare action log, the
  gray-zone log, override and spawn audits) survive. That is probably right, but
  nothing records it as a decision.

**Design only.** This change inventories every location an entity's data can live
in and recommends, for each, whether decommission backs it up, deletes it or keeps
it, with the reason checked against the docs, the CAL licence and the welfare and
audit needs. No code changes here; the owner reviews the decisions first.

## What Changes

- `design.md` holds the inventory (state, data, Redis, Qdrant, sqlite-vec, the
  append-only file, backups and preservation bundles, volumes) with a decision and
  reason for each location, the principles the decisions follow, and the
  implementation outline.
- A spec delta for `entity-decommission` states the target behaviour: the backup
  covers the complete cognitive state; deletion covers every content-bearing
  location of this entity and only this entity; welfare, audit and research-metric
  records are kept by design; a failure to reach a store is a failure; every run
  leaves a content-free audit record.
- `tasks.md` lists the review gate and the implementation steps that follow it.

## Capabilities

### Modified Capabilities

- `entity-decommission`: complete backup coverage, complete and entity-scoped
  deletion, kept records named, failures fatal, an audit record.

## Impact

- Review only. The implementation touches `kaine/lifecycle/decommission.py`,
  `kaine/lifecycle/__main__.py`, the backup manifest and the docs on decommission
  (docs/11-preservation.md, docs/13-security-and-privacy.md).
