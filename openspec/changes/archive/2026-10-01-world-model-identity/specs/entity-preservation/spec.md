## ADDED Requirements

### Requirement: Fork and merge snapshots carry module artifacts
`ForkManager` SHALL support two optional module hooks, `export_snapshot_artifacts(dest_dir)` and `import_snapshot_artifacts(src_dir)`, and SHALL keep each module's artifacts in `<snapshot root>/<snapshot id>/artifacts/<module name>/`, with owner-only permissions (directories 0700, files 0600).

- **snapshot** SHALL call every module's export hook before writing `snapshot.json`, and SHALL record each hook's returned record under the snapshot metadata `artifacts`. If any export raises, the snapshot SHALL fail and SHALL leave no snapshot directory behind.
- **fork** SHALL copy the parent's artifact directories, except those of shed modules, into the child's own snapshot directory, so every fork owns an independent copy.
- **restore** SHALL call every module's import hook with that module's artifact directory, whether or not it exists. An import error SHALL propagate.
- **merge** SHALL refuse with an error when both parents carry Phantasia artifacts, unless the caller passes `world_model_from="a"` or `world_model_from="b"`. With a choice given, or when at most one parent carries them, merge SHALL copy each module's artifacts from the parent that has them (the chosen one for Phantasia) and record the source per module in the merged snapshot's metadata.

#### Scenario: Fork copies are independent
- **WHEN** a snapshot with Phantasia artifacts is forked twice
- **THEN** each child's snapshot directory holds its own copy of the artifacts, and changing one copy leaves the other and the parent's unchanged

#### Scenario: A failed export leaves no snapshot
- **WHEN** a module's export hook raises during `snapshot`
- **THEN** `snapshot` raises and no snapshot directory for that id remains

#### Scenario: Shed modules are not copied
- **WHEN** a fork sheds Phantasia
- **THEN** the child's snapshot has no Phantasia artifacts

#### Scenario: Merge refuses to pick a world model by accident
- **WHEN** both parents carry Phantasia artifacts and no `world_model_from` is given
- **THEN** merge raises an error naming the choice to make, and writes no merged snapshot

#### Scenario: Merge with a named world model
- **WHEN** both parents carry Phantasia artifacts and `world_model_from="b"` is given
- **THEN** the merged snapshot carries parent b's Phantasia artifacts and its metadata records that source
