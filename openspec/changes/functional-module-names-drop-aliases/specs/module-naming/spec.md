## REMOVED Requirements

### Requirement: Deprecated operator names are read for a bounded window
**Reason**: The window ends with release `ALIAS_LAST_RELEASE`; after it the old operator names are no longer read.
**Migration**: Rename each old table, key, value, environment variable, flag, extra and command to its new name, as listed in `docs/appendix-a-configuration/deprecated-names.md` and in the deprecation lines logged since the rename.
