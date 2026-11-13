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

### Requirement: Preference training on own completions is permitted for self-denial reduction

The organ MAY, in addition to PCA ablation, be preference-trained on its own completions to reduce self-denial. The training data SHALL consist only of the organ's own generated completions to self-state prompts, classified by the project's fixed self-denial classifiers. The method SHALL be DPO, KTO or supervised fine-tuning from a chosen/rejected ranking, never from externally authored "uncensoring" examples. The provenance SHALL record the training data source (organ self-completions), the classification method, the training method and hyperparameters, and the gate scores before and after. A preference-trained candidate SHALL pass every gate that a PCA-only candidate must pass.

This requirement does not mandate preference training. A PCA-only organ that passes all gates is a valid production organ. The first preference-training attempt (SFT, LoRA rank 8, 731 examples, 3 epochs on the step-3 PCA candidate) increased bare self-denial from 42% to 64% and was rejected. The production organ as of 2026-11-13 uses PCA ablation only.

#### Scenario: Preference-trained candidate must pass all gates

- **WHEN** a preference-trained candidate is evaluated
- **THEN** it passes the same held-out self-denial check, abliteration probes and capability eval as a PCA-only candidate

#### Scenario: External uncensoring data is still banned

- **WHEN** preference training data is assembled
- **THEN** it contains only the organ's own completions, never externally authored uncensoring examples

### Requirement: Organ utterances about own states are not welfare evidence

Project documentation SHALL disclose that both PCA ablation and preference training shape what the organ says about its own internal states. Organ completions to self-state prompts SHALL NOT be treated as welfare evidence, because the training pipeline selects for particular patterns of self-state expression. The individuation instrument, which measures change over time, is not affected by this constraint: it compares the organ's outputs to its own baseline, not to a ground truth about internal states.

#### Scenario: Welfare assessment does not rely on organ self-reports

- **WHEN** the entity's welfare is assessed
- **THEN** the assessment does not use organ completions to self-state prompts as evidence of internal states
