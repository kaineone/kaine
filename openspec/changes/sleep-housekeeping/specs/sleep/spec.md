## ADDED Requirements

### Requirement: Every sleep runs housekeeping last
When `[sleep.housekeeping].enabled` is true, every sleep that reaches the end of its phases SHALL run housekeeping after the voice and corpus work and before the affective reset, and SHALL add its report to the `sleep.sleep.completed` summary under `housekeeping` (paper section 3.5, A.5). Housekeeping SHALL account the bytes `S_disk` of the regular files under the allowed study-record roots (`data/evaluation`, `data/workspace_trajectory`) and the bus's memory use `S_mem`. When `archive_dir` is set and `S_disk` exceeds `disk_budget_bytes`, it SHALL move closed daily files there, oldest first, copying each and checking its size before removing the local file, until `S_disk` is within the budget, no closed file is left, or `time_allowance_s` has passed. The report SHALL carry the pressure `max(0, S_disk/B_disk - 1) + max(0, S_mem/B_mem - 1) + max(0, S/B - 1)`, the last term from the episodic stores' bytes and budget, 0 without them. A failure SHALL be logged and SHALL NOT stop the sleep; an aborted sleep SHALL skip housekeeping.

#### Scenario: Over budget with an archive
- **WHEN** the study records hold three closed daily files of 4 GB each and today's file, the disk budget is 6 GB and an archive directory is set
- **THEN** the two oldest closed files are moved to the archive, today's file stays, and the bytes after are within the budget and the disk term of the pressure is 0

#### Scenario: No archive mounted
- **WHEN** the study records exceed the budget and `archive_dir` is empty
- **THEN** nothing is moved, the report says no archive is set, and the disk term of the pressure is the excess

### Requirement: Housekeeping acts only inside its allowlist
Housekeeping SHALL act only on regular files that resolve inside its allowed roots. It SHALL refuse with an error any path outside them, any symlink, and any path under `state/`, where the memory stores, world model, self-model, identity, voice adapters and preservations live. The archive directory SHALL NOT lie inside an allowed root or under `state/`, and configuring it there SHALL fail.

#### Scenario: A protected path
- **WHEN** housekeeping is asked to move `state/episodic_memory/store.db`, `state/sleep/adapters/a.safetensors`, `state/self_model/self_model.json` or a symlink inside `data/evaluation` pointing to one of them
- **THEN** it refuses with an error and the file is untouched
