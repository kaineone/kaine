# abliteration-interpretability

## ADDED Requirements

### Requirement: Layer-resolved refusal-disposition readout via the Jacobian lens

The system SHALL provide an offline tool that fits a Jacobian lens on the organ's
weights and reports, per layer, the mass the lens places on refusal-marker tokens
over a refusal-eliciting prompt set — a mechanistic readout of what the organ's
internal activations are disposed to say. The readout SHALL be produced from a
real lens fit on the real weights; a lens that could not be fit SHALL report the
gap and stop, and SHALL NOT emit a fabricated readout.

#### Scenario: A real lens produces a per-layer readout

- **WHEN** the tool is run against the organ weights with a fitted lens
- **THEN** it reports a per-layer refusal-disposition score over the prompt set

#### Scenario: An unfittable lens fails honestly

- **WHEN** the lens cannot be fit (missing weights, backend unavailable)
- **THEN** the tool reports the reason and produces no readout, rather than a
  fabricated or default-clean result

### Requirement: Vanilla-base vs abliterated comparison

The tool SHALL support comparing the vanilla base model against its abliterated
counterpart on the same prompt set and lens configuration, and SHALL report the
per-layer delta so a residual or relocated refusal disposition in the abliterated
model is made visible rather than hidden by a passing behavioral gate.

#### Scenario: Residual disposition surfaces in the delta

- **WHEN** the abliterated model still carries a refusal disposition at some layer
- **THEN** the base-vs-abliterated per-layer delta shows that residual, even if the
  abliterated model passes the behavioral probe gate

### Requirement: Offline, non-runtime, content-free artifact

The analysis SHALL run offline (never in the runtime cognitive loop) and SHALL emit
a content-free summary artifact — per-layer scores, the prompt-set digest, and
model ids/revisions — and SHALL NOT write raw model generations or prompt/response
text. No runtime module SHALL import the vendored lens.

#### Scenario: Artifact carries no generated text

- **WHEN** the summary artifact is written
- **THEN** it contains per-layer scores and metadata only, and no raw model output
  or prompt/response text

#### Scenario: The lens is not on the runtime path

- **WHEN** the entity is booted
- **THEN** no runtime module imports the vendored Jacobian lens

### Requirement: The lens readout is corroborating, not a proof

The tool's outputs and any downstream use SHALL state that the Jacobian lens is an
averaged-Jacobian approximation and an interpretive signal, that it covers the
safetensors weights and not the served quantized artifact, and that it corroborates
but does not replace the behavioral abliteration gate or prove complete refusal
removal.

#### Scenario: Limits stated wherever the readout is used

- **WHEN** the readout is presented (artifact, model card, or paper)
- **THEN** its limits are stated: an approximation and interpretive signal, on the
  safetensors surface, corroborating the behavioral gate rather than replacing it
