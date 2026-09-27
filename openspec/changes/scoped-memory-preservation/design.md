## Decisions

### Scope by the being's own names, not by what the server holds
- `MemoryStorage.export(collections: Sequence[str])` takes the collection names to export and returns only those that exist.
  - Qdrant scrolls exactly those names.
  - sqlite-vec filters its `SELECT` with `WHERE m.collection IN (...)`.
  - In-memory filters its dictionary.
  - There is no default and no argument meaning "everything", so a caller cannot sweep a shared server by accident.
- `MnemosCore.export_state` passes its persisted collection names (`collection_name(kind)` for each kind except `short_term`).

### Import by kind, replacing the target
- `MnemosCore.import_state(state)`:
  - `src_prefix = state["collection_prefix"]`, falling back to `"mnemos_"` for bundles that lack it.
  - For each `(name, points)` in `state["persisted"]`: if `name == src_prefix + kind` for a persisted kind, the target is `self.collection_name(kind)`. Anything else is skipped, with one INFO log line per skipped collection naming it and its point count, never its content.
  - Every persisted kind is mapped, including a kind the bundle lacks. A missing kind means the preserved being had none: sqlite-vec exports only collections that hold rows, so its target is emptied.
  - Every point for every mapped kind is validated before anything is written: the vector dimension equals the storage's, and the vector is finite.
  - A bundle whose persisted collections hold points, none of them under the bundle's own prefix, is refused (`StorageError`) rather than revived with no memories.
  - Only a missing `collection_prefix` key falls back to `"mnemos_"`. An empty prefix is a real prefix.
  - The short-term buffer is rebuilt only after every persisted replace succeeds.
  - If a replace fails after earlier kinds were replaced, the replaced kinds are named in an ERROR log before the error propagates.
  - Then, for each mapped kind, `storage.replace_collection(target, points)` runs.
  - A failure at any point raises `StorageError`, and preservation refuses the revive.
- `replace_collection(name, points)` on each backend:
  - **Qdrant:** delete the collection if it exists, create it with the storage's size and distance, upsert in batches of 256.
  - **sqlite-vec:** in one transaction, delete the collection's `vec_memories` rows through a subquery on `memories` (no bound variable per row), then its `memories` rows, then insert.
  - **In-memory:** replace the list.
  - The old `import_` is removed. Its only callers are `MnemosCore.import_state` and tests.
- **Why replace rather than merge.** Revive means "become this preserved individual". The collections under the reviving being's prefix belong to that being. Their current contents are either identical to the bundle (the usual next step of a study line) or post-bundle writes from a failed step, which the retry must not inherit. The bundle stays on disk, untouched.

### Empatheia
- `QdrantAgentStore.all_profiles()` scrolls its collection (payload only, no vectors), parses `profile_json` into `AgentModel`s, and overlays the cache, which is authoritative for anything touched since boot.
  - A scroll failure raises. Preservation must fail loudly rather than emit a partial profile set.
  - The in-memory store returns its dictionary.
- `Empatheia.export_preservation_state()` returns `{"profiles": {id: model.to_dict()}}` from `all_profiles()`. `_capture_module_state` merges it over `serialize()`, as it does for Mnemos.
- `Empatheia.import_preservation_state(state)` runs `deserialize` (the cache), then `put`s every profile, which re-embeds it with the running embedder and writes it to the configured collection.
  - Before writing, it replaces its collection's contents: it deletes and recreates the collection in the Qdrant store, and clears the in-memory store. This mirrors Mnemos's replace semantics.
  - It returns the number of profiles restored.
  - The Qdrant store's writes (`put`, `replace_all`) share one `asyncio.Lock`, so a `put` from a running consumer cannot interleave with a replace. `initialize` is idempotent and always ensures the collection, including when a client was injected.

### Revive routes each module to its own importer
- A module declares `preservation_state_key`, the key in its captured state that `preservation.revive` routes to its `import_preservation_state`: `"memory_state"` for Mnemos, `"profiles"` for Empatheia.
- Modules without the key are restored through `deserialize`, as before.
- The "a revive that would drop a captured component raises" check applies unchanged.

## Verification
- Two Mnemos cores with prefixes `a_` and `b_` on one fake Qdrant client (the existing test fake, extended for `delete_collection`) and on one sqlite-vec file:
  - `a`'s export holds only `a_*`.
  - Importing `a`'s state into a core with prefix `c_` writes `c_*` and leaves `b_*` unchanged.
- An old-style state holding `b_*` and `empatheia_agents` besides `a_*` imports only `a_*` kinds and logs the skipped names.
- Replace semantics: extra points in the target before import are gone afterwards, and a validation failure leaves the target untouched.
- Empatheia: profiles only in the collection (not the cache) are captured. Import restores them into a different configured collection with re-embedded vectors. A scroll failure raises.
- End to end through `preserve_live` and `revive` with the in-memory backends.
