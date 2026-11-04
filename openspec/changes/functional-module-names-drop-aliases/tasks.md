## 1. Before removal

- [x] 1.1 Check the window rule against the releases cut: name the release that shipped the rename, the second release after it, and the date 90 days after it. If 27.02 meets neither bound, move `ALIAS_LAST_RELEASE` later, regenerate `docs/appendix-a-configuration/deprecated-names.md`, and stop here until that release is out.
  - **Result (2026-11-04):** No releases have been cut. The rename merged 2026-10-14 (PR #505). The window rule requires the second release after the rename and 90 days. With zero releases, 27.02 cannot meet either bound. All tasks in sections 2 and 3 are blocked until the first release is cut and 27.02 (or a later value) satisfies both conditions. `ALIAS_LAST_RELEASE` stays at 27.02.

## 2. Removal

- [ ] 2.1 The configuration loader refuses an old table, key or listed value with an error naming the new name.
- [ ] 2.2 Remove the old environment variables, command-line flags and plugin seam names.
- [ ] 2.3 Remove the `kaine[nexus]` extra and the `kaine.nexus` and `kaine.lifecycle.mnemos_recover` shims.
- [ ] 2.4 Remove the old session-key header and the browser storage migration.
- [ ] 2.5 `compose/kaine.yml` reads only the new variable names.
- [ ] 2.6 Remove the operator entries from `kaine/legacy_names.py` and the exclusions that only they needed (the configuration-loading spec leaves `OLD_NAME_SECTION_FILES` once its old-name requirement is removed); the module-names guard keeps passing.

## 3. Tests and docs

- [ ] 3.1 Tests: each kind of old name is refused with the new name in the error; the persisted readers and `rename_state` behave as before.
- [ ] 3.2 Docs: the deprecated-names page and its generator, appendix E's operator names, the CHANGELOG.
- [ ] 3.3 `openspec validate functional-module-names-drop-aliases --strict`.
