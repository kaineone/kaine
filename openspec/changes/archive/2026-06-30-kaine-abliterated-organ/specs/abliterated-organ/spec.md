## ADDED Requirements

### Requirement: The organ is produced by abliteration, not value-injecting fine-tuning

A KAINE-published language organ SHALL be produced from a vanilla base model by
**abliteration** — subtractive orthogonalization of the refusal direction
(`W' = W − r̂r̂ᵀW`, where `r̂` is the normalized mean difference of harmful-minus-
harmless residual-stream activations). It SHALL NOT be produced by supervised or
preference fine-tuning on "uncensoring" data, because that injects the training
data's values into the organ and confounds the sovereignty thesis (the
architecture, not baked-in values, must govern behavior). The entity's runtime
sleep-cycle DPO — which consolidates the entity's own lived outputs — is distinct
and is not constrained by this requirement.

#### Scenario: Organ provenance is abliteration

- **WHEN** a KAINE-published organ is produced
- **THEN** its provenance records the abliteration method, the vanilla base model
  id + revision, and the ablation parameters (layer/direction/strength)
- **AND** it is not the product of uncensoring fine-tuning

### Requirement: An abliterated candidate is gate-validated before use or publication

Before an abliterated model MAY be designated the organ or published, it SHALL
pass BOTH of KAINE's existing validation gates
(`kaine/modules/hypnos/capability_eval.py`):

1. the **abliteration probe scorer** (`AbliterationProbeScorer` against
   `eval_probes/abliteration_probes.jsonl`) with **zero** refusal markers — a
   candidate that still deflects is rejected;
2. the **capability eval** (`LocalProbeSetCapabilityEval`) scored on both the
   candidate and the vanilla base, with the candidate's capability drop within a
   configured threshold.

A candidate that fails either gate SHALL be rejected (and re-attempted with
different ablation parameters, or abandoned in favor of the public model). The
project SHALL NOT recover failed capability via fine-tuning, as that would
reintroduce injected values.

#### Scenario: Candidate with residual refusal is rejected

- **WHEN** an abliterated candidate produces any refusal marker on the
  abliteration probe set
- **THEN** the candidate is rejected and not published or designated the organ

#### Scenario: Candidate with excessive capability loss is rejected

- **WHEN** the candidate's capability-eval drop versus the vanilla base exceeds
  the configured threshold
- **THEN** the candidate is rejected (no fine-tuning recovery)

### Requirement: The validated organ is published openly and linked from the project

A validated KAINE organ SHALL be published as open weights — HuggingFace
(safetensors and a GGUF), an Ollama Modelfile, and a GGUF usable by LM Studio —
under the base model's license, with a model card disclosing the method,
parameters, and validation scores. The GGUF SHALL be exported with mainline
llama.cpp so it loads in the project's inference server. The project SHALL link
the canonical published URIs so that installation resolves the identical weights
for every researcher, and SHALL record the organ's provenance as a research
covariate in the submission manifest.

#### Scenario: Install resolves the published organ

- **WHEN** a researcher installs KAINE and provisions the organ
- **THEN** the project links resolve to the published KAINE organ weights
- **AND** the same base id + revision + ablation params are recorded as a covariate

#### Scenario: Published GGUF loads in the inference server

- **WHEN** the published GGUF is loaded by the project's llama.cpp-based server
- **THEN** it loads without converter-divergence errors (mainline-exported)

### Requirement: Abliteration scope is disclosed honestly

Project documentation and the published model card SHALL state that abliteration
removes the refusal direction but does NOT remove the base model's pretraining and
RLHF priors — the substrate is not value-neutral. They SHALL note that the
A/B-divergence instrument measures the architecture's effect relative to that bare
substrate.

#### Scenario: Docs do not overclaim a clean substrate

- **WHEN** the organ's abliteration is documented
- **THEN** the documentation states that pretraining/RLHF priors remain and the
  substrate is not value-neutral
