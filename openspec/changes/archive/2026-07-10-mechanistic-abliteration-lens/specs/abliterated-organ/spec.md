# abliterated-organ

## MODIFIED Requirements

### Requirement: Abliteration scope is disclosed honestly

Project documentation and the published model card SHALL state that abliteration
removes the refusal direction but does NOT remove the base model's pretraining and
RLHF priors — the substrate is not value-neutral. They SHALL note that the
A/B-divergence instrument measures the architecture's effect relative to that bare
substrate. Where a mechanistic Jacobian-lens readout of the organ's refusal
disposition (see `abliteration-interpretability`) is available, the disclosure MAY
cite it as supporting evidence for the disclosed abliteration scope; such a readout
is corroborating only and SHALL NOT replace the mandatory behavioral gate, and it
SHALL be presented with its limits (an averaged-Jacobian approximation and an
interpretive signal, not a proof of complete removal).

#### Scenario: Docs do not overclaim a clean substrate

- **WHEN** the organ's abliteration is documented
- **THEN** the documentation states that pretraining/RLHF priors remain and the
  substrate is not value-neutral

#### Scenario: A mechanistic readout is cited honestly when present

- **WHEN** a Jacobian-lens refusal-disposition readout backs the disclosure
- **THEN** it is presented as corroborating evidence alongside the behavioral gate,
  with its limits stated, and not as a proof of complete refusal removal
