## ADDED Requirements

### Requirement: An existing state volume upgrades without a manual ownership fix
The deployment SHALL mount no volume inside the entity-state volume whose parent directory might not exist there, so the container runtime never creates a root-owned directory inside the state tree. The cycle SHALL find the voice-alignment jobs directory at a mount point outside the state volume. A state volume written by an earlier release SHALL start under the current release, run as the image's non-root user, without the operator changing any ownership.

#### Scenario: Upgrading a volume written before the module rename
- **WHEN** the cycle starts on a state volume that holds an entity under the old module directories and has no `sleep/` directory
- **THEN** the state rename completes, the entity runs, and a second start finds nothing to rename
