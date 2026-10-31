## ADDED Requirements

### Requirement: The model card is generated from the organ's provenance record

The published organ's model card SHALL be rendered from a template in the repository and the organ's provenance record. The card's method and coverage statements SHALL list exactly the tensor families and layers the provenance record says were edited.

#### Scenario: Coverage follows the record

- **WHEN** the provenance record lists MLP down-projections and full-attention output projections for layers 11 to 31, and no linear-attention output projections
- **THEN** the rendered card names those families and layers and states that linear-attention outputs were not edited

### Requirement: The model card states the dual-use risk

The rendered card SHALL include a dual-use section stating that refusal behaviour was removed, that the weights may comply with requests the base model refuses, that they are not evaluated or intended for standalone deployment, that the removal method is also published as a jailbreak, and how to report misuse. The card SHALL NOT carry the tag `uncensored`.

#### Scenario: Dual-use section present

- **WHEN** the card is rendered from any valid provenance record
- **THEN** it contains the dual-use section with each of those statements and no `uncensored` tag

### Requirement: Published organ weights are gated with a use agreement

Every repository through which the project distributes refusal-ablated organ weights SHALL require acceptance of the project's use agreement before download. Uploading, gating and agreement changes SHALL be performed by the operator, not by an automated agent.

#### Scenario: A new organ release is gated

- **WHEN** the operator publishes a new ablated organ
- **THEN** its repository is gated with the use agreement before the weights are made visible

### Requirement: The KAINE-only adapter is never merged into published weights

The organ's KAINE-only LoRA adapter SHALL NOT be merged into any published organ weights. If the adapter is published, it SHALL be published separately under the Cognitive Architecture License and behind the same use agreement.

#### Scenario: Published base carries no adapter

- **WHEN** the published organ weights are compared with the ablation-only candidate they were built from
- **THEN** they are identical, and no adapter tensors are present
