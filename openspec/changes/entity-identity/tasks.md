## 1. Identity

- [ ] 1.1 `kaine/lifecycle/identity.py` with the design API; atomic owner-only writes; malformed input raises `IdentityError`.
- [ ] 1.2 Tests: the frozen format and legacy derivation (golden values), mint uniqueness, fork lineage, legacy determinism, the load/save round-trip, refusal to overwrite a different ID, and malformed files.

## 2. Snapshots, forks and preservation

- [ ] 2.1 `ForkManager.snapshot` and `preserve_live` record the identity in metadata. `fork` records the child's forked identity. `merge` keeps the target's identity and records `merged_from`.
- [ ] 2.2 Revive restores the bundle's identity, derives the legacy identity for a bundle without one, and refuses a conflicting identity file.
- [ ] 2.2a Plaintext identity sidecars (design D7): `state/forks/<id>/identity.json`, the preservation and decommission `manifest.json`, and forked-being job payloads. Loading checks that the sidecar agrees with the in-snapshot identity.
- [ ] 2.3 Tests on real bundles written by `preserve_live` in a temporary tree: with an identity, without one (legacy, deterministic across two revivals), and with a conflict.

## 3. Spawn and history

- [ ] 3.1 The cycle start path resolves the identity before the developmental stage. It never mints when prior lived history exists.
- [ ] 3.2 `has_prior_lived_history_in_lineage`, with tests: another being's bundle does not count, this being's and an ancestor's do, and an unknown identity counts as lived.
- [ ] 3.3 `openspec validate entity-identity --strict`.
