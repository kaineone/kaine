## ADDED Requirements

### Requirement: Predictive processors share one predictive unit
The vision, audition and interoception forward models SHALL derive from one `ForwardModelBase` and SHALL return a `PredictionResult` that carries its value, whether it is defined, its null-baseline value and whether the reading was skipped. The mapping from a result to intensity SHALL be one shared function, parameterised per processor where today's processors differ.

#### Scenario: Migration does not change what a processor publishes
- **WHEN** a processor is driven over the recorded seeds and inputs before and after its migration
- **THEN** the digest of every published `prediction_error`, `own_error`, intensity, salience, welfare reading and `state_dict` is identical

#### Scenario: An undefined reading is never read as zero surprise
- **WHEN** a processor's step has no defined error
- **THEN** its result has `defined = False` and `value = None`, and no consumer default can read it as defined

### Requirement: The workspace finds processors through a registry
Each predictive processor SHALL register its name, report type and feature dimension in a boundary-neutral registry. Workspace feedback and the content level SHALL read the processor roster from it.

#### Scenario: Three processors blend exactly as before
- **WHEN** workspace feedback runs with vision, audition and interoception registered
- **THEN** the blend weights equal the weights the hard-coded three-processor code produced
