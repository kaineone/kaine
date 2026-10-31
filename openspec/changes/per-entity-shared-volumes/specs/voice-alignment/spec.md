# Spec Delta

## ADDED Requirements

### Requirement: Shared adapter and job volumes are partitioned by entity
When the organ-adapters directory or the trainer-jobs directory may be shared between entities, the system SHALL write each entity's promoted adapters, adapter manifest and voice-alignment jobs under a subdirectory named by that entity's id, and SHALL record the entity id in each job's description.

#### Scenario: Two entities promote adapters into one volume
- **WHEN** the main entity and a study line each promote a voice adapter into the same organ-adapters volume
- **THEN** each adapter and its manifest are under that entity's own subdirectory, and neither overwrites the other's files

#### Scenario: A job names its owner
- **WHEN** the voice-alignment phase writes a training job into a shared jobs directory
- **THEN** the job is under the entity's subdirectory and its description records the entity id

#### Scenario: An entity id that is not an identity
- **WHEN** an entity id does not match the identity format
- **THEN** it is never used as a directory name, and the write or the load is refused

#### Scenario: Legacy flat layout
- **WHEN** the volume holds only the earlier flat layout (`active.json` and `active-N.gguf` at the root)
- **THEN** the organ still loads the adapter it names, and the trainer service still runs root-level jobs

### Requirement: The organ loads only the pointed entity's own adapter
The organ SHALL load the adapter named by a volume-level pointer that identifies the entity, and SHALL load it only when the target's real path lies under the subdirectory of the entity the pointer names, refusing absolute paths and `..`.

#### Scenario: A pointer that leaves the volume
- **WHEN** the volume-level pointer names a file outside the organ-adapters volume
- **THEN** the organ loads no adapter and logs why
