## ADDED Requirements

### Requirement: An existing state volume upgrades without a manual ownership fix
The deployment SHALL mount no volume inside the entity-state volume whose parent directory might not exist there, so the container runtime never creates a root-owned directory inside the state tree. The cycle SHALL find the voice-alignment jobs directory at a mount point outside the state volume. A state volume written by an earlier release SHALL start under the current release, run as the image's non-root user, without the operator changing any ownership.

#### Scenario: Upgrading a volume written before the module rename
- **WHEN** the cycle starts on a state volume that holds an entity under the old module directories and has no `sleep/` directory
- **THEN** the state rename completes, the entity runs, and a second start finds nothing to rename

### Requirement: Every reader of the jobs directory resolves it the same way
The voice-alignment jobs directory SHALL be resolved by one function, from `KAINE_TRAINER_JOBS_DIR` when it is set, then `[sleep.voice_alignment].trainer_jobs_dir`, then `state/sleep/voice_align_jobs`. The sleep module, decommission and the pre-boot report SHALL use it. Decommission SHALL attribute a job written before the upgrade to its entity when the job records paths under the old state layout or the old jobs mount path, and SHALL resolve a relative recorded path against the job's own directory.

#### Scenario: Decommission in the container finds the jobs volume
- **WHEN** the cycle's jobs directory comes from `KAINE_TRAINER_JOBS_DIR=/trainer-jobs` and a decommission runs with the same environment
- **THEN** decommission lists and attributes the jobs in `/trainer-jobs`

#### Scenario: A job written under the old layout
- **WHEN** a job's `job.json` records its adapter output directory under the old sleep module directory (`/app/state/<old sleep directory>/adapters`) and the entity's adapters now live in `state/sleep/adapters`
- **THEN** decommission attributes the job to the entity

