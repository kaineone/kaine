## ADDED Requirements

### Requirement: Every sleep runs housekeeping last
When `[sleep.housekeeping].enabled` is true, every sleep that reaches the end of its phases SHALL run housekeeping after the voice and corpus work and before the affective reset, and SHALL add its report to the `sleep.sleep.completed` summary under `housekeeping` (paper section 3.5, A.5). Housekeeping SHALL account the bytes `S_disk` of the regular files under the allowed study-record roots (`data/evaluation`, `data/workspace_trajectory`) and of the current process-log backups, and the bus's memory use `S_mem`. While `S_disk` exceeds `disk_budget_bytes`, it SHALL walk those files oldest first, deleting log backups and exporting closed daily study-record files to `archive_dir` (copy, SHA-256 check, rename) before removing the local copy, until `S_disk` is within the budget, nothing is left to reclaim, or `time_allowance_s` has passed. A study record SHALL NOT be deleted unless an archive copy with the same SHA-256 exists; with no archive set, study records SHALL stay. The report's terms SHALL be handed to the housekeeping pressure. The report SHALL carry the pressure `max(0, S_disk/B_disk - 1) + max(0, S_mem/B_mem - 1) + max(0, S/B - 1)`, the last term from the episodic stores' bytes and budget, 0 without them. A failure SHALL be logged and SHALL NOT stop the sleep; an aborted sleep SHALL skip housekeeping.

#### Scenario: Over budget with an archive
- **WHEN** the study records hold three closed daily files of 4 GB each and today's file, the disk budget is 6 GB and an archive directory is set
- **THEN** the two oldest closed files are moved to the archive, today's file stays, and the bytes after are within the budget and the disk term of the pressure is 0

#### Scenario: No archive mounted
- **WHEN** the study records exceed the budget and `archive_dir` is empty
- **THEN** no study record is moved or deleted, the report says no archive is set, and the disk term of the pressure is the excess

### Requirement: Housekeeping acts only inside its allowlist
Housekeeping, in sleep and in the awake floor, SHALL act only on regular files that resolve inside its allowed roots or are current process-log backups outside `state/`. It SHALL refuse with an error any path outside them, any symlink, and any path under `state/`, where the memory stores, world model, self-model, identity, voice adapters and preservations live. The archive directory SHALL NOT lie inside an allowed root or under `state/`, and configuring it there SHALL fail.

#### Scenario: A protected path
- **WHEN** housekeeping is asked to move `state/episodic_memory/store.db`, `state/sleep/adapters/a.safetensors`, `state/self_model/self_model.json` or a symlink inside `data/evaluation` pointing to one of them
- **THEN** it refuses with an error and the file is untouched

### Requirement: The awake floor keeps free space above a reserve
While the entity is awake and housekeeping is enabled, the cycle SHALL check every `floor_period_s` the free space of the `data` and `state` volumes, once per filesystem, against `R^hk = max(reserve_bytes, reserve_share x volume size)` (paper A.5). Below `R^hk` it SHALL reclaim regenerable data oldest first, never exporting and never deleting an unexported study record, until free space reaches `2 R^hk`, and SHALL then add the disk's excess over its budget to the pressure until the next sleep. If free space is still below `R^hk` it SHALL suspend the study record: each study-record sink SHALL write one gap-start marker and drop entries until the floor resumes the record once free space is back at `2 R^hk`, then write a gap-end marker with the count dropped. Each action SHALL be logged and published on `housekeeping.out` with labels and byte counts only.

#### Scenario: Reclaim is enough
- **WHEN** a volume falls below its reserve and deleting log backups brings it above `R^hk`
- **THEN** the floor publishes a reclaim action and the study record continues

#### Scenario: The disk stays full
- **WHEN** reclaiming leaves free space below `R^hk`
- **THEN** the study record is suspended with a gap marker, and it resumes with an end marker once free space is back at `2 R^hk`

### Requirement: The archive side follows no links
Before removing a local study record, housekeeping SHALL refuse that file, keeping the local copy, when the archive destination or any path component between the archive root and it is a symlink, when the destination resolves outside the archive, when it is the same file as the source, or when a non-regular file sits at the temporary name. Every archive-side step below the archive root SHALL go through directory descriptors opened without following links, and an archive root that does not exist SHALL be treated as not mounted. It SHALL create the temporary file exclusively without following links, read every digest through a descriptor that does not follow links, re-verify the destination's digest after the rename and before the removal, sync the destination directory, and re-check with `lstat` that every file it removes is a regular file.

#### Scenario: The destination is a link to the source
- **WHEN** the archive destination of a closed study record is a symlink to that record
- **THEN** the export is refused, the local record stays and the pass goes on with the next file
