## 1. Identity persistence

- [ ] 1.1 The readout reads `self_rhythm_identity.json` and, on a non-revive boot, adopts a valid stored identity into the self-rhythm before building its key.
- [ ] 1.2 The readout writes the current identity to the file on every start (after a revive this is the bundle's identity).
- [ ] 1.3 The cycle passes whether the boot is a revive to the readout.
- [ ] 1.4 Decommission backs up and deletes `self_rhythm_identity.json`.

## 2. Tests

- [ ] 2.1 A restart with the same state directory and a fresh self-rhythm keeps the identity and restores awake time and passes.
- [ ] 2.2 A revive boot keeps the restored identity and overwrites the stored file.
- [ ] 2.3 Progress saved for another entity is still ignored.
- [ ] 2.4 A malformed identity file is ignored and rewritten.

## 3. Docs

- [ ] 3.1 Update `docs/06-operation/development.md` and `docs/appendix-a-configuration/perception-and-sleep.md`.
