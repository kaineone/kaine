## 1. Identity

- [x] 1.1 `kaine/lifecycle/identity.py` with the design API; atomic owner-only writes; malformed input raises `IdentityError`.
- [x] 1.2 Tests: the frozen format and legacy derivation (golden values), mint uniqueness, fork lineage, legacy determinism, the load/save round-trip, refusal to overwrite a different ID, and malformed files.

## 2. Snapshots, forks and preservation

- [x] 2.1 `ForkManager.snapshot` and `preserve_live` record the identity in metadata. `fork` records the child's forked identity. `merge` keeps the target's identity and records `merged_from_entity`.
- [x] 2.2 Revive restores the bundle's identity, derives the legacy identity for a bundle without one, and refuses a conflicting identity file.
- [x] 2.2a Plaintext identity sidecars (design D7): `state/forks/<id>/identity.json`, the preservation and decommission `manifest.json`, and forked-being job payloads. Loading checks that the sidecar agrees with the in-snapshot identity.
- [x] 2.2b Every `IdentityError` is raised before any state is modified, and revive never writes to the bundle (D10). Test: a conflicting revive leaves the target tree and the bundle byte-identical.
- [x] 2.3 Tests on real bundles written by `preserve_live` in a temporary tree: with an identity, without one (legacy, deterministic across two revivals), and with a conflict.

## 3. Spawn and history

- [x] 3.1 The cycle start path resolves the identity before the developmental stage from this tree's own lived artifacts (design D4), never from `state/forks` or `state/preservation`. Test: a fresh spawn with foreign fork snapshots and bundles under `state/` mints an ID and resolves to gestation. Test: a legacy tree resolves, a snapshot is then taken in the same boot, and the next resolution yields the same ID (D10).
- [ ] 3.2 `has_prior_lived_history_in_lineage`, with tests: another being's bundle does not count, this being's and an ancestor's do, and an unknown identity counts as lived.
- [ ] 3.3 `openspec validate entity-identity --strict`.
