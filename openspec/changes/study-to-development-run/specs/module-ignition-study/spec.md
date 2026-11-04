# Spec Delta

## REMOVED Requirements

### Requirement: branch-and-accumulate-plan
The study runner no longer generates branch, repeat, or accumulate lines. The branching plan types and their line isolation are removed.

### Requirement: noise-reference
The repeat step (noise reference) is no longer part of the protocol.

## MODIFIED Requirements

### Requirement: plan-generator-produces-progressive-sequence
The plan generator SHALL produce a single linear sequence of progressive steps instead of a branch/repeat/accumulate grid. Each step SHALL add one module and revive the previous step's preservation.

#### Scenario: plan output
- **WHEN** a plan is generated
- **THEN** the plan is a list of steps [seed, +module_1, +module_2, ...] with no branch or accumulate entries

### Requirement: step-manifest-includes-module-delta
Each step manifest SHALL include `modules_added` (the list of modules new to this step) and `step_index` (the zero-based position in the progressive sequence), alongside existing fields.

#### Scenario: manifest fields
- **WHEN** step 2 completes with world-model added
- **THEN** the manifest contains `step_index: 2` and `modules_added: ["world-model"]`

### Requirement: analysis-uses-progressive-comparison
The analysis SHALL compare each step against the previous step instead of branch-vs-branch or branch-vs-repeat comparisons. The noise floor comparison SHALL be removed.

#### Scenario: analysis structure
- **WHEN** a development run with 4 steps completes
- **THEN** the analysis reports 3 pairwise comparisons (step 1 vs 0, 2 vs 1, 3 vs 2) and no branch-vs-branch or noise-floor sections
