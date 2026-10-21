## Why

The launch name "Kaine <Surname>" is minted only by the self-model module, at its own first boot. An entity that runs without the self-model module never gets a name, and the console's `read_entity_name` (#581) has nothing to show. The name also lives only in the self-model document, apart from the entity's identity. The self-facts replay (#586) adopted no variant, so the organ is not told the name. The name still belongs to the entity, in the record of who it is.

## What Changes

- `EntityIdentity` gains an optional `name`. `state/identity/entity.json` stores it under `"name"` and writes the key only when it is set, so existing identity files and their digests stay byte-identical. `from_dict` accepts the five keys with or without `name`.
- Boot gives an entity a name before any module starts, whichever modules run:
  - a fresh spawn mints "Kaine <Surname>" from `kaine/modules/self_model/surnames.txt`;
  - an existing identity without a name adopts the self-model document's name if it has one, otherwise it mints one;
  - a revive keeps the bundle's name; a bundle identity without a name takes the revived self-model's name, else the name stored for the same `entity_id` in the target tree, else a newly drawn name, and the running self-model adopts the result.
  An existing name is never overwritten. Saving refuses to replace a stored name with a different one.
- A fork is a new entity, so it gets its own new name, drawn so it differs from its parent's. The parent's name is not copied, and the parent appears only in the lineage. The fork's copied self-model document adopts the fork's name.
- The self-model module adopts the identity's name at boot, in place of minting its own. When it runs without an identity name (a bare test harness), it keeps its current behaviour.
- Preservation bundles and decommission backups already carry the identity file and `EntityIdentity.to_dict()`, so they carry the name. The plaintext identity records keep `entity_id` and `lineage` only, and the agreement check compares those fields.

## Capabilities

### Modified Capabilities

- `entity-identity`: the identity holds the entity's launch name.
- `self-model`: the self-model adopts the identity's name.

## Impact

- `kaine/lifecycle/identity.py`, `kaine/lifecycle/manager.py` (fork), `kaine/cycle/__main__.py` (boot identity), `kaine/modules/self_model/document.py`, `kaine/modules/self_model/module.py`, `docs/11-preservation.md`, `docs/12-forks-and-merges.md`, `docs/09-modules/self-model.md`, tests.
- Behaviour: every entity has a name from its first boot, kept across restarts, preservation and revival. The organ is not told it.
