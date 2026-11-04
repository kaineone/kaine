# Spec Delta

## Purpose
The development run protocol governs the single-entity progressive run: one entity boots, develops, gains modules in order, and watches the film programme after each addition, with recording and analysis at every step.

## ADDED Requirements

### Requirement: progressive-step-sequence
The development run SHALL execute steps in a fixed linear order. Step 0 is the seed (development and maturation). Each subsequent step SHALL revive the previous step's preserved entity with one additional module enabled, in the declared module order, then play the film programme.

#### Scenario: step ordering
- **WHEN** the run plan is generated for modules [episodic-memory, world-model, planning]
- **THEN** step 0 is the seed, step 1 adds episodic-memory, step 2 adds world-model, step 3 adds planning, each reviving the previous step's preservation

#### Scenario: step 0 is development
- **WHEN** step 0 begins
- **THEN** a new entity is spawned with the base module set, enters the local stimulus source, and matures under the default gate

### Requirement: per-step-isolation
Each step SHALL have its own working directory, bus database, and memory collection prefix. No two steps SHALL share state beyond the preserved entity bundle passed from the previous step.

#### Scenario: step directories are distinct
- **WHEN** steps 0 and 1 execute
- **THEN** their working directories, bus database numbers, and collection prefixes are all different

### Requirement: module-addition-via-revive
Each post-seed step SHALL revive the previous step's preserved entity with one more module enabled. The revived entity's module set MUST be the previous set plus exactly one new module.

#### Scenario: single module addition
- **WHEN** step k revives step k-1's preservation
- **THEN** the entity's enabled modules differ by exactly one module from step k-1

### Requirement: recording-per-step
Every step SHALL record workspace trajectory, ignition log, dashboard data (privacy-filtered), and language utterances into the step's working directory. Inner speech MUST NOT be recorded. Each step SHALL produce a manifest listing what was recorded.

#### Scenario: recording coverage
- **WHEN** a step completes
- **THEN** the step manifest lists trajectory, ignition log, dashboard and utterance files, all within the step's directory

### Requirement: broadcast-capacity-configurable
The development run SHALL accept a `broadcast_capacity` parameter that sets the workspace's K (number of simultaneous winners per broadcast). The default SHALL be the value from the shipped configuration.

#### Scenario: explicit capacity override
- **WHEN** the run plan sets `broadcast_capacity = 3`
- **THEN** every step's overlay sets `[workspace].broadcast_capacity = 3`

### Requirement: progressive-analysis
The analysis SHALL compare each step against the previous step: ignition rate, coalition membership, and any new modules appearing in winning coalitions. The analysis report SHALL list each step with its module delta and ignition metrics.

#### Scenario: step-over-step comparison
- **WHEN** steps 0 through 3 complete
- **THEN** the analysis compares step 1 vs 0, step 2 vs 1, step 3 vs 2, and produces a per-step delta report
