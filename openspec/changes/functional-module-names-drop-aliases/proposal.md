## Why

The functional-module-names change kept the old operator-facing names working for a bounded window, so configuration files, units and scripts written before the upgrade keep working across it. Each use logs a deprecation line naming the last release that reads the old name: `ALIAS_LAST_RELEASE` in `kaine/legacy_names.py`, set to 27.02 by the window rule (the second release after the one that ships the rename, and no earlier than 90 days after it). Once that release is out, the aliases only cost: every reader keeps two spellings, the guard keeps exclusions for them, and a typo in an old name still loads silently under the new one.

## What Changes

- **The window rule is checked first.** Before anything is removed, the releases actually cut are compared with the rule. If 27.02 is earlier than the second release after the rename or than 90 days after it, `ALIAS_LAST_RELEASE` moves later, the deprecated-names page is regenerated, and this change waits.
- **Old configuration names are refused.** A configuration layer that uses an old table, key or listed value fails to load with an error naming the new name, instead of being read under it.
- **Operator aliases are removed.** The old environment variables, command-line flags and plugin seam names, the `kaine[nexus]` extra, the `python -m kaine.nexus` and `python -m kaine.lifecycle.mnemos_recover` shims, the old session-key header, the browser storage migration and the old variable names in `compose/kaine.yml` go.
- **Stored names stay readable.** Nothing in the persisted scope changes: the readers of preservation bundles, snapshots, checkpoints and recorded datasets under old names, `kaine.lifecycle.rename_state` and its revert, and the dashboard record's data directory and volume.

## Capabilities

### Modified Capabilities

- `module-naming`: the window for old operator names ends.
- `configuration-loading`: a layer that uses an old name fails to load instead of being normalized.

## Impact

- **Code:** `kaine/legacy_aliases.py` (`getenv`, `add_cli_aliases`, `normalize_config_layer`), `kaine/legacy_names.py` (the operator entries and their exclusions), `kaine/dashboard/auth.py`, `kaine/nexus/`, `kaine/lifecycle/mnemos_recover.py`, `kaine/dashboard/static/dashboard_legacy_storage.js`, `pyproject.toml`, `compose/kaine.yml`, `scripts/prepare-headless-host.sh`.
- **Operators:** a file or unit that still uses an old name stops at start with an error naming the new one. The deprecation lines logged since the rename name each such use.
- **Docs:** `docs/appendix-a-configuration/deprecated-names.md` and its generator, appendix E's operator names, the CHANGELOG.
