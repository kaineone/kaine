## 1. Design (this change)

- [x] 1.1 Measure where each old name occurs, by category, with the false positives and the collisions with target names (design.md, "Survey").
- [x] 1.2 Record the codemod, the compatibility decisions, the PR sequence and the tests; add the ROADMAP row.

## 2. Codemod and mapping table (PR 1)

- [x] 2.1 `kaine/legacy_names.py`: the mapping, the developmental phrases, the compound overrides, the alias tables and the per-entry scope status, as pure data with no imports.
- [x] 2.2 `tools/maintainer/rename_modules.py`: scopes, `--only`, `--apply`, `--check`, `git mv` moves, the exclusion list, the context rules, the collision check, the review queue and the sorted dry-run report.
- [x] 2.3 Fixture tests: each rule and scope, each known false positive unchanged, exclusions untouched, the `SequenceModule` alias, idempotence, a byte-identical report on two runs, injectivity of the table.
- [x] 2.4 `tests/test_module_names_guard.py` with every scope pending.
- [x] 2.5 Commit the survey script as `rename_modules.py --survey`, which prints the table in design.md.

## 3. Collision pre-renames (PR 2)

- [x] 3.1 `WorldModel` protocol to `WorldModelBackend`.
- [x] 3.2 `SelfModel` document class to `SelfModelDocument`.

## 4. Docs prose (PR 3)

- [x] 4.1 `--scope prose` over the book, READMEs, live spec prose and active-change prose; resolve the review queue with overrides.
- [x] 4.2 Move the 18 `docs/09-modules/` pages and add the "Module names" page mapping old names to new ones.
- [x] 4.3 Set `[individuation].disclosure` in `config/kaine.toml` to the owner's text (10.4) by hand, outside the codemod, with the docs that quote it.

## 5. Compatibility readers (PR 4)

- [x] 5.1 Config: per-layer normalization of tables, keys and values before the merge, one warning line per layer, both names in one layer refused, the study allowlist and the unknown-key guard after normalization.
- [x] 5.2 Environment variables: one lookup helper, the warning, refusal when old and new are both set and differ.
- [x] 5.3 CLI aliases for `--serve-nexus`, `--db-gestation`, `--gestation-budget-seconds`; plugin seam aliases.
- [x] 5.4 Read-maps for bundles, snapshots and fork sidecars (module keys, manifest `modules`, the `gestation/` member, stage values and fields) and for recorded datasets (stream names, `source`, per-module fields, sidecar directories).
- [x] 5.5 `kaine.lifecycle.rename_state`: state paths, file names, the stage file, the sqlite-vec file and `collection` column, Qdrant aliases, a move manifest with `--revert`, refusal of an old-and-new pair.
- [x] 5.6 Never-regress: `_coerce_stage` reads `gestation` as `development`; `OWN_LIVED_ARTIFACTS` lists old and new paths.
- [x] 5.7 Fail closed on an unrecognized stage value: `_coerce_stage` no longer reads an unknown or non-string value as `embodied`; the stage reader raises, and the cycle refuses to boot with a message naming the stage file and the value's `repr` (truncated to 64 characters). Independent of the `gestation` alias. Tests: a garbled value, a forward-versioned value, a non-string value, and the file left unchanged.
- [x] 5.8 Tests for 5.1 to 5.6 with synthetic table entries, plus import of the four local bundles and the nine local fork trees.

## 6. Identifiers by layer (PRs 5a to 5d)

- [x] 6.1 Vision, Interoception, Sequence.
- [x] 6.2 Affect, Sleep, Episodic memory, World model.
- [x] 6.3 Language, Vocal, Planning, Action selection, Effectors, Self-model, Social cognition, Workspace.
- [x] 6.4 Embodiment, Perceptual locus, Supervisor, Dashboard, Recorder and the developmental terms, with the gate files that name moved tests.

## 7. Keys and wire names (PR 6)

- [x] 7.0 Prerequisites (PR 6a): complete the config-key table and readers, normalize raw TOML readers, keep stored and UI strings out of the keys run, decide the queued matches and collisions, refuse a plugin seam under two names, audit stream cursors and Redis persistence, pin stored tags, and prove the flip in a scratch tree (fast suite, slow lane, dry boot, old-bundle revive, checkpoint load, dashboard smoke).
- [x] 7.1 Module `name` values, streams and event types, config tables, keys and values in the shipped config, profiles and studies, plugin seams, `STUDY_ALLOWED_TABLES`.
- [x] 7.2 Live spec folder names and the matching delta folders in active changes.
- [x] 7.3 Mark the config, seam, bundle-key and dataset aliases live; the kaine-cl1 plugin uses the new seams.
- [x] 7.4 The one-time cleanup of old-named streams (`python -m kaine.bus.legacy_streams`: the full old-to-new map, length and memory per stream, a typed confirmation, live streams never deleted) and its preboot warning; the history fallbacks (the language module's `sleep_index` backfill falls back to the old sleep stream when the new one has no sleep event; the dashboard's conversation history reads the old stream, then the new one, until the cleanup removes it); `"config_key_scheme": 2` in run manifests; a dry-boot test with an old-named overlay and study.

## 8. Operator surface (PR 7)

- [x] 8.0 Prerequisites: the dashboard accepts the old session-key header `X-Nexus-Session-Key` beside the new `X-Dashboard-Session-Key` for the deprecation window, logging one line per process, and the browser sends the new one; the browser reads each storage key under its new name, falls back to the old name, writes the new name and removes the old one on first load; the compose file falls back to each old variable in `compose/.env`; the headless-host script keeps `--serve-nexus` as a hidden alias that warns; the record volume keeps its name; the queued matches are decided.
- [x] 8.1 Environment variables, CLI flags and their help text, the `dashboard` extra with `nexus` kept as an alias, the `python -m kaine.nexus` shim.
- [x] 8.2 Quadlet and compose names; volume names unchanged; the installer refuses while the old unit runs and removes the old unit file it installed.
- [x] 8.3 Dashboard UI strings: the JavaScript globals, the session-key header, the browser storage keys, the session cookie, the `OPERATOR_EXACT` strings (template variables, the health block key, the runtime keys the supervisor banner reads), display labels and operator-facing messages.
- [x] 8.4 Follow-ups from the 6b review: the old-stream cleanup and its preboot row take "now" from the Redis clock (`TIME`), and the preboot path treats an unreadable newest entry as recent; setup returns "conflict" with a clear message when the secrets file has both the new and the old dashboard table.
- [x] 8.5 Proof: the operator guard is clean, the gate is green, a dashboard smoke passes with the new header and storage keys, and a sweep of the test diffs finds no old and new literals that collapsed into one name.

## 9. Persisted names (PR 8)

- [x] 9.0 Prerequisites: list `individuation/birth_pending` and the other persisted names the earlier steps found; every reader of a stored value (stage value and fields, freeze source, lock holder, preservation reason, study outcome, checkpoint header, encoder version, record fields, the episodic memory module's stored collection prefix) maps the old value on read; the study runner reads `birth_bloom_ends_at` through the stage reader; the queued matches are decided.
- [x] 9.1 State paths, file names, collection names and stage values in code; `rename_state` runs at boot under the state lock before the identity and stage reads, with the configured Qdrant client or `no_qdrant=True`, and on a revived or merged fork tree and an extracted bundle before import. A tree that holds an old and a new name for one item fails the boot and changes nothing; a migrated tree is a no-op.
- [x] 9.2 Check that the K1-Jev gold files and `data/evaluation/` are byte-identical before and after.
- [x] 9.3 Proof: a state tree written by main is upgraded and booted with nothing lost, and a second boot is a no-op; bundles and world-model checkpoints written before the rename revive and load byte-equal; the `womb_params_digest` golden and the stage round-trip are unchanged; decommission finds and deletes both forms; a dry boot of an old-named study; the guard is clean for every scope but prose; the gate is green; a sweep of the test diffs finds no collapsed literals.
- [x] 9.4 Docs: rolling back across this step is unsupported; preserve and stop the cycle on the earlier release (`python -m kaine.cycle.control preserve --stop`), copy the data root, and restore that copy to go back.

## 10. Close-out (PR 9)

- [x] 10.1 The guard turns strict for every scope: the prose scope is applied and marked done, so every scope's clean check, the capitalized-name scan and the identifier scan (10.5) run on every pull request. `CHANGELOG.md` and the generated deprecated-names page join the exclusion list, since both name the old names on purpose.
- [x] 10.2 CHANGELOG `[Unreleased]` entry; the configuration appendix lists each deprecated name and the last release that reads it. `ALIAS_LAST_RELEASE` is 27.02 by the window rule (the rename ships in 26.10 at the earliest). `docs/appendix-a-configuration/deprecated-names.md` is generated from the table by `tools/maintainer/gen_deprecated_names.py`, and a test keeps it current.
- [x] 10.3 Open `functional-module-names-drop-aliases` for the operator aliases.
- [x] 10.5 Sweep comments and docstrings that name a renamed function, class or keyword argument (`make_lingua`, `_phase_volition`, `make_hypnos`, the red-team harness docstring's `praxis_factory`, and the rest), and add a grep-based check that none remain. The check is `test_no_identifier_names_an_old_module`: no snake_case identifier outside the excluded files has an old module or developmental key as one of its parts, apart from `GUARD_KEPT_IDENTIFIERS`. The sweep also fixed the comments, UI strings and pointers the codemod kept (the dashboard's maturation strings and freeze-source list, the vendored InternVideo-Next pointer comments, change paths that moved to the archive) and phrases an earlier step had doubled ("Self-model self-model", "sleep sleep", the world-model merge message).
- [x] 10.4 **Owner decision (decided 2026-10-11):** `[individuation].disclosure` becomes "You are periodically and privately assessed for how much you have changed since you first woke, for your own protection. The assessment never enters your experience." It is entity-facing text, so the codemod never touches it; the change lands by hand in task 4.3.
- [x] 10.6 Follow-up from the PR 8 review: an old directory that holds only empty mount points, at any depth, plans no removal step, so a leftover mount does not report a migration and grow the manifest on every start; the removal step removes only directories whose whole subtree holds no file, no symlink and no mount point.
