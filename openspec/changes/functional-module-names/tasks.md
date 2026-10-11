## 1. Design (this change)

- [x] 1.1 Measure where each old name occurs, by category, with the false positives and the collisions with target names (design.md, "Survey").
- [x] 1.2 Record the codemod, the compatibility decisions, the PR sequence and the tests; add the ROADMAP row.

## 2. Codemod and mapping table (PR 1)

- [ ] 2.1 `kaine/legacy_names.py`: the mapping, the developmental phrases, the compound overrides, the alias tables and the per-entry scope status, as pure data with no imports.
- [ ] 2.2 `tools/maintainer/rename_modules.py`: scopes, `--only`, `--apply`, `--check`, `git mv` moves, the exclusion list, the context rules, the collision check, the review queue and the sorted dry-run report.
- [ ] 2.3 Fixture tests: each rule and scope, each known false positive unchanged, exclusions untouched, the `SequenceModule` alias, idempotence, a byte-identical report on two runs, injectivity of the table.
- [ ] 2.4 `tests/test_module_names_guard.py` with every scope pending.
- [ ] 2.5 Commit the survey script as `rename_modules.py --survey`, which prints the table in design.md.

## 3. Collision pre-renames (PR 2)

- [ ] 3.1 `WorldModel` protocol to `WorldModelBackend`.
- [ ] 3.2 `SelfModel` document class to `SelfModelDocument`.

## 4. Docs prose (PR 3)

- [ ] 4.1 `--scope prose` over the book, READMEs, live spec prose and active-change prose; resolve the review queue with overrides.
- [ ] 4.2 Move the 18 `docs/09-modules/` pages and add the "Module names" page mapping old names to new ones.

## 5. Compatibility readers (PR 4)

- [ ] 5.1 Config: per-layer normalization of tables, keys and values before the merge, one warning line per layer, both names in one layer refused, the study allowlist and the unknown-key guard after normalization.
- [ ] 5.2 Environment variables: one lookup helper, the warning, refusal when old and new are both set and differ.
- [ ] 5.3 CLI aliases for `--serve-nexus`, `--db-gestation`, `--gestation-budget-seconds`; plugin seam aliases.
- [ ] 5.4 Read-maps for bundles, snapshots and fork sidecars (module keys, manifest `modules`, the `gestation/` member, stage values and fields) and for recorded datasets (stream names, `source`, per-module fields, sidecar directories).
- [ ] 5.5 `kaine.lifecycle.rename_state`: state paths, file names, the stage file, the sqlite-vec file and `collection` column, Qdrant aliases, a move manifest with `--revert`, refusal of an old-and-new pair.
- [ ] 5.6 Never-regress: `_coerce_stage` reads `gestation` as `development`; `OWN_LIVED_ARTIFACTS` lists old and new paths.
- [ ] 5.7 Fail closed on an unrecognized stage value: `_coerce_stage` no longer reads an unknown or non-string value as `embodied`; the stage reader raises, and the cycle refuses to boot with a message naming the stage file and the value's `repr` (truncated to 64 characters). Independent of the `gestation` alias. Tests: a garbled value, a forward-versioned value, a non-string value, and the file left unchanged.
- [ ] 5.8 Tests for 5.1 to 5.6 with synthetic table entries, plus import of the four local bundles and the nine local fork trees.

## 6. Identifiers by layer (PRs 5a to 5d)

- [ ] 6.1 Vision, Interoception, Sequence.
- [ ] 6.2 Affect, Sleep, Episodic memory, World model.
- [ ] 6.3 Language, Vocal, Planning, Action selection, Effectors, Self-model, Social cognition, Workspace.
- [ ] 6.4 Embodiment, Perceptual locus, Supervisor, Dashboard, Recorder and the developmental terms, with the gate files that name moved tests.

## 7. Keys and wire names (PR 6)

- [ ] 7.1 Module `name` values, streams and event types, config tables, keys and values in the shipped config, profiles and studies, plugin seams, `STUDY_ALLOWED_TABLES`.
- [ ] 7.2 Live spec folder names and the matching delta folders in active changes.
- [ ] 7.3 Mark the config, seam, bundle-key and dataset aliases live; the kaine-cl1 plugin uses the new seams.

## 8. Operator surface (PR 7)

- [ ] 8.1 Environment variables, CLI flags, the `dashboard` extra with `nexus` kept as an alias, the `python -m kaine.nexus` shim.
- [ ] 8.2 Quadlet and compose names; volume names unchanged; the installer removes the old unit it installed.
- [ ] 8.3 Dashboard UI strings.

## 9. Persisted names (PR 8)

- [ ] 9.1 State paths, file names, collection names and stage values in code; `rename_state` runs at boot.
- [ ] 9.2 Check that the K1-Jev gold files and `data/evaluation/` are byte-identical before and after.

## 10. Close-out (PR 9)

- [ ] 10.1 The guard turns strict for every scope.
- [ ] 10.2 CHANGELOG `[Unreleased]` entry; the configuration appendix lists each deprecated name and the last release that reads it.
- [ ] 10.3 Open `functional-module-names-drop-aliases` for the operator aliases.
- [ ] 10.4 **Owner decision:** whether `[individuation].disclosure` keeps "since your birth"; it is entity-facing text and stays out of the codemod.
