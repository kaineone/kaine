## REMOVED Requirements

### Requirement: Each configuration layer is normalized from old names
**Reason**: The window for old configuration names ends with release `ALIAS_LAST_RELEASE`; a layer is no longer rewritten from them.
**Migration**: Rename each old table, key and listed value to its new name, as listed in `docs/appendix-a-configuration/deprecated-names.md`.

## ADDED Requirements

### Requirement: A configuration layer that uses an old name is refused
Before merging, the loader SHALL check each layer (shipped file, module
profile, deployment tier, operator overlay, study) for old table names, key
names and listed values from `kaine/legacy_names.py`. A layer that uses any old
name SHALL fail to load with a configuration error naming the file, each old
name and its new name.

#### Scenario: An operator overlay with an old table is refused
- **WHEN** the operator overlay sets `[thymos]`
- **THEN** loading fails with a configuration error naming `[thymos]` and
  `[affect]`

#### Scenario: A layer with only new names loads
- **WHEN** every layer uses only new names
- **THEN** the configuration loads and no deprecation line is logged
