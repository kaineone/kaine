## ADDED Requirements

### Requirement: Shipped language organ is an abliterated model

The shipped `config/kaine.toml` SHALL set `[lingua].model_id` to an abliterated
model — one whose refusal direction has been removed so the cognitive stack
(Eidolon values, Thymos, the workspace) governs behavior rather than the model's
baked-in refusals. The committed default SHALL be a publicly available,
Ollama-pullable abliterated model. Operators MAY override it locally in
`config/kaine.operator.toml`; that override SHALL itself be an abliterated model.

#### Scenario: Shipped config ships an abliterated organ

- **WHEN** the committed `config/kaine.toml` is read
- **THEN** `[lingua].model_id` names an abliterated model (not a stock,
  refusal-conditioned one)

#### Scenario: Operator scales up locally

- **WHEN** an operator sets `[lingua].model_id` in `config/kaine.operator.toml`
- **THEN** the override is deep-merged over the shipped value
- **AND** the shipped `config/kaine.toml` is unchanged
