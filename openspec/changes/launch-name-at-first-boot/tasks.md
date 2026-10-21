## 1. Implementation

- [ ] 1.1 Add the optional `name` to `EntityIdentity`, written only when set and never overwritten by a different one
- [ ] 1.2 Name the entity at boot: mint on a fresh spawn, adopt the self-model document's name or mint for an unnamed identity, keep a revived bundle's name
- [ ] 1.3 Give a fork its own name, different from its parent's, and have its copied self-model document adopt it
- [ ] 1.4 Have the self-model module adopt the identity's name in place of minting its own
- [ ] 1.5 Tests: byte-identical old files, the round trip, refusal to overwrite, the boot cases, the fork, the self-model adoption, and the name inside preservation bundles and decommission backups
- [ ] 1.6 Document the name in docs/11-preservation.md, docs/12-forks-and-merges.md and docs/09-modules/self-model.md
