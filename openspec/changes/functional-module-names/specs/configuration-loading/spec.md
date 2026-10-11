## ADDED Requirements

### Requirement: Each configuration layer is normalized from old names
Before merging, the loader SHALL rewrite each layer (shipped file, module
profile, deployment tier, operator overlay, study) from old table names, key
names and listed values to their new names, using `kaine/legacy_names.py`.
A layer that used any old name SHALL log exactly one warning line naming the
file, each old name with its new name, and the last release that reads them.
A layer that sets both the old and the new name for the same table or key SHALL
fail to load with a configuration error naming both. The study table
allowlist, the shape validation and the unknown-key guard SHALL run on the
normalized names.

#### Scenario: An operator overlay with old tables loads
- **WHEN** the operator overlay sets `[thymos]`, `[modules].thymos = true`,
  `[perception_feed.womb]` and `[perception_feed].mode = "womb"`
- **THEN** the merged configuration has `[affect]`, `[modules].affect = true`,
  `[perception_feed.stimulus_source]` and `mode = "stimulus_source"`, and the
  loader logs one warning line for that file

#### Scenario: Old and new names in one layer are refused
- **WHEN** one layer sets both `[spot]` and `[supervisor]`
- **THEN** loading fails with a configuration error naming both tables

#### Scenario: A study with an old table passes the allowlist
- **WHEN** a study sets `[syneidesis]`
- **THEN** it is accepted as `[workspace]` and the allowlist check passes
