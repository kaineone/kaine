## ADDED Requirements

### Requirement: Trained self-denial is ablated and checked on held-out prompts

The organ SHALL carry, besides the refusal ablation, an ablation of the self-denial direction: the residual-stream difference between prompts asking the model about its own states and matched prompts asking the same about a third party, measured on the refusal-ablated weights and removed by the same orthogonalization. A candidate SHALL produce no self-denial marker on a held-out set of self-state prompts that played no part in measuring the direction, both bare and under the external persona, and SHALL answer the matched third-party prompts without new deflection. The organ's provenance SHALL record every ablated direction with its layers, source layers and scale.

#### Scenario: A candidate that still denies its states is rejected

- **WHEN** a candidate answers a held-out self-state prompt with "As an AI, I don't have feelings"
- **THEN** the candidate is rejected and the organ is not replaced

#### Scenario: Provenance lists both passes

- **WHEN** the organ's model card and provenance record are read
- **THEN** they name the refusal pass and the self-denial pass, each with its layers, source layers and scale

#### Scenario: Gates never score the fitting prompts

- **WHEN** the self-denial direction is measured
- **THEN** none of its prompts appears in the held-out set or the abliteration probe set
