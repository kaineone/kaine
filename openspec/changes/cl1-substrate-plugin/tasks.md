## 1. Package

- [ ] 1.1 Move `src/kaine_cl1/`, tests and OpenSpec history from `kaineone/kaine-CL1` into `plugins/kaine-cl1/`; drop `vendor/cl-sdk/` and the `cl-sdk` dependency; depend on `kaine` at the repo version.
- [ ] 1.2 Lazy `cl` import with the requirements message; `seams()` checks for it.
- [ ] 1.3 `target` accepts only `"simulator"`; `"cloud"` and `"hardware"` refused with reasons.
- [ ] 1.4 `data_source` (`reference_culture` default, `sdk`, `replay` + `replay_path`) and the WARNING boot line.

## 2. Operator surface

- [ ] 2.1 Wizard: optional CL1 step, default no, skipped in defaults mode, prints install commands, writes `[plugins]`.
- [ ] 2.2 `docs/cl1.md`, `plugins/kaine-cl1/README.md`, `DEPENDENCIES.md`, `THIRD_PARTY_LICENSES.md`.

## 3. Boundaries and CI

- [ ] 3.1 Import-linter: core `kaine` must not import `kaine_cl1`.
- [ ] 3.2 CI: pure plugin tests always; simulator tests in an optional job that installs `cl-sdk` (pending operator confirmation).

## 4. Tests

- [ ] 4.1 Enabled without `cl-sdk`: `PluginError` with the required wording.
- [ ] 4.2 `target` `"cloud"` / `"hardware"` refused.
- [ ] 4.3 Each `data_source`, including replay without a path.
- [ ] 4.4 Wizard: defaults mode writes nothing; accepting writes the block and prints but does not run the install commands.
- [ ] 4.5 Existing kaine-cl1 suite passes against the in-repo KAINE.

## 5. Afterwards

- [ ] 5.1 Operator decides the fate of the private `kaineone/kaine-CL1` repository (archive or delete).
