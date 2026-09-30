## ADDED Requirements

### Requirement: One root for all growing data
When `[storage].data_root` is set, every component that writes growing data SHALL write it under that root. That covers entity state, workspace trajectories, evaluation output, research events, backups, native Redis and Qdrant data, and downloaded models. Configured relative paths SHALL resolve against the data root instead of the working directory. Absolute paths the operator sets explicitly SHALL keep their value. When `[storage].data_root` is absent, paths SHALL resolve as they do today.

#### Scenario: Relative paths follow the root
- **WHEN** `[storage].data_root` is set and `[evaluation].trajectory_dir` is the relative default
- **THEN** trajectories are written under the data root

#### Scenario: No storage section
- **WHEN** the operator config has no `[storage]` section
- **THEN** every path resolves exactly as before this change

### Requirement: Pre-boot checks free space at the data root
The pre-boot check SHALL include a `Storage` row. It SHALL PASS when the data root's filesystem has at least `[storage].min_free_gb` free, and FAIL otherwise. The message SHALL name the free and required space.

#### Scenario: Data root nearly full
- **WHEN** the data root's filesystem has less free space than the configured minimum
- **THEN** the `Storage` row fails and names the free and required space
