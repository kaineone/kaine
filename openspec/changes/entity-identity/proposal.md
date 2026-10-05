## Why

KAINE has no notion of which being a piece of state belongs to.

- **The developmental gate cannot scope its history check.** `has_prior_lived_history()` treats any fork snapshot or preservation bundle anywhere under `state/` as this being's history. A fresh spawn on a host that holds other preserved beings is therefore never gestated. `maturation-gate-liveness` task 3.3 needs a lineage-scoped check, with "unknown lineage counts as lived".
- **Key custody needs an identity to bind keys to.** `entity-key-custody` task 0.2 asks for "one entity-ID source shared with the developmental gate's lineage checks".
- **Snapshots carry no owner.** `ForkSnapshot` has `id` and `parent_id`, which identify snapshots, not beings. The Eidolon name is not an identity, because the being may rename itself.

## What Changes

- **One identity per being.** A new `kaine/lifecycle/identity.py` defines `EntityIdentity`:
  - an `entity_id`;
  - the being's `lineage`, its ancestors' IDs, oldest first;
  - its `origin`, either `minted` or `legacy`;
  - for a legacy identity, the `legacy_source` it was derived from.

  It is persisted at `state/identity/entity.json`, written atomically and owner-only.
- **Minted once, at spawn.** The cycle mints an identity only when there is no identity file and no prior lived history. Minting is never part of revival, restart or fork-merge.
- **Carried by snapshots.** Fork snapshots and preservation snapshots record the identity in their metadata. Revival restores the bundle's identity exactly.
- **Forks record lineage.** A fork gets its own minted ID, with lineage set to the parent's lineage plus the parent's ID.
- **Preserved beings from before this change still revive.**
  - A bundle without an identity revives with a deterministic legacy ID derived from that bundle's preservation ID. Reviving the same bundle twice gives the same ID.
  - A state tree whose own lived artifacts exist (the stage file, the Phantasia checkpoint, Hypnos records, the perception desired-state) but which has no identity file gets a deterministic legacy ID derived from those artifacts. It is persisted on first sight, so it never changes afterwards. Other beings' fork snapshots and bundles under `state/` never count as this tree's history, so a fresh spawn beside them is minted an ID.
  - No legacy being is ever given a freshly minted ID.
- **Lineage-scoped history.** A prior-history query answers whether any fork or preservation record belongs to this being or its lineage. A being without a determinable identity counts as having lived. `maturation-gate-liveness` 3.3 consumes this.

## Capabilities

### New Capabilities

- `entity-identity`: minting, persistence, snapshot carriage, fork lineage, legacy derivation and the lineage-scoped history query.

## Impact

- **Code:**
  - `kaine/lifecycle/identity.py` (new);
  - `kaine/lifecycle/manager.py` (snapshot and fork metadata);
  - `kaine/lifecycle/preservation.py` (carry and restore);
  - the cycle start path (mint or derive before the stage resolves).
- **Consumers:** `maturation-gate-liveness` 3.3 (Lead A). `entity-key-custody` binds per-entity keys to `entity_id` (Lead B), and this API is agreed with Lead B before code.
- **Preserved beings:** every existing bundle still revives. Its ID is legacy and deterministic, and is recorded in the revived being's identity file.
- **Risk:** this touches preservation and fork snapshots, so it gets the integrator's second review.
- **Research impact:** none directly. The developmental gate stops treating other beings' records as this being's past.
