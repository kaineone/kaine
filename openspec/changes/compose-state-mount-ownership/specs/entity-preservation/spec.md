## ADDED Requirements

### Requirement: The state rename refuses before moving when it cannot write a destination
Before its first step, the boot-time state rename SHALL check that it can write every directory its steps write into, checking the nearest existing ancestor of a directory it will create. When the old side of a move holds data and the new side is an empty mount point, the refusal SHALL say that the new side is a mount point, and this check SHALL take precedence over the write check. When a directory is not writable, the start SHALL stop with the rename-refused exit code and a message that names the directory, its owner and its mode, and SHALL move nothing.

#### Scenario: A root-owned destination directory
- **WHEN** the state tree has a `sleep/` directory owned by root and not writable by the cycle's user, and `hypnos/` holds files
- **THEN** the start stops with the rename-refused exit code, the message names `sleep/`, its owner and mode, and no file has moved

#### Scenario: Data on the old side, an empty mount point on the new side
- **WHEN** `hypnos/voice_align_jobs` holds a file and `sleep/voice_align_jobs` is an empty mount point
- **THEN** the refusal says that `sleep/voice_align_jobs` is a mount point a move cannot land on
