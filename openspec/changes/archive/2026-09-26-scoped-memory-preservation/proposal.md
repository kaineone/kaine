## Why

Preservation is meant to capture one individual. Mnemos's Qdrant export does not stop at that individual. `QdrantStorage.export()` lists every collection on the Qdrant server and dumps them all into the bundle. On any server that holds more than one being, which includes the two lines of the module-ignition study, one being's preservation therefore carries another being's memories. That breaks the isolation the study depends on, and it breaks mental privacy between beings.

Revive has two matching defects:
- **It writes collections back under their original names**, not the reviving being's prefix.
  - A study line reviving the gestation bundle writes into the gestation line's collections, which it never reads, so it wakes without its memories.
  - Both lines revive from that one bundle, so they write into the same collections.
  - Reviving an old bundle that swept up another being's collections would overwrite that being's live memories with an older copy.
- **It only upserts.** Points written after the bundle (a failed step that is then retried from the same bundle) survive, so the retry does not start from the preserved individual.

Empatheia has no preservation hook of its own. Its agent profiles reach a Qdrant bundle only because Mnemos's unscoped export sweeps them up. Its `serialize()` holds only profiles cached since boot.

## What Changes

- **Mnemos exports only its own collections**: its prefix plus each memory kind (`MNEMOS_COLLECTION_KINDS`), for every storage backend. A bundle records the prefix, as it does today.
- **Mnemos imports by kind into its own prefix.**
  - Each persisted collection in a bundle is mapped from `<bundle prefix><kind>` to `<own prefix><kind>`.
  - For each kind in the bundle, the target collection's contents are replaced by the bundle's points. Every point is validated first; the target is emptied and the bundle's points written only after validation passes.
  - Collections in a bundle that are not the bundle's own memory kinds (another being's, or Empatheia's in older bundles) are never imported. They are logged by name and point count.
- **Empatheia preserves itself.**
  - `export_preservation_state` reads every profile from its own collection, not just the cached ones, merged with the cache.
  - `import_preservation_state` writes them back through its own store into its configured collection, re-embedding each profile with the running embedder.
  - Its preservation state is its profiles, so no vectors cross between beings or embedding spaces.
- **Nothing else changes.** Decommission already names only the being's own collections.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `entity-preservation`: a bundle holds only the preserved being's memories; revive restores them into the reviving being's own collections, exactly as preserved.
- `empatheia`: Empatheia captures and restores its own agent profiles in preservation.

## Impact

- `kaine/modules/mnemos/storage.py`: `export(collections)` and `replace_collection` on all three backends.
- `kaine/modules/mnemos/memory.py`: scoped export and import by kind.
- `kaine/modules/empatheia/module.py` and `store.py`: preservation hooks and a full profile scan.
- Tests, including two prefixes on one server.
- Existing bundles still revive: their own memory kinds are imported under the new prefix. Foreign collections are skipped and named in the log, and Empatheia's profiles come from the bundle's `profiles`.
