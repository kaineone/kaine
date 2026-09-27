## 1. Mnemos

- [x] 1.1 `export(collections)` on the Qdrant, sqlite-vec and in-memory storages; `MnemosCore.export_state` passes its own collection names.
- [x] 1.2 `replace_collection` on the three storages; `MnemosCore.import_state` maps by kind to its own prefix, validates first, replaces, and skips and logs foreign collections; `import_` removed.

## 2. Empatheia

- [x] 2.1 `all_profiles()` on both stores; `export_preservation_state` and `import_preservation_state` with replace semantics and re-embedding.

## 3. Verification

- [x] 3.1 Tests: two prefixes on one Qdrant fake and one sqlite-vec file; old-style bundle; replace semantics; validation-before-write; Empatheia capture of uncached profiles and restore into another collection; preserve and revive end to end.
- [x] 3.2 Offline suite green; `openspec validate scoped-memory-preservation --strict`.
