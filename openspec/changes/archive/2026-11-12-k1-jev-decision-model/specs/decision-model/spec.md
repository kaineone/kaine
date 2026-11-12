## ADDED Requirements

### Requirement: The decision model judges external speech against a frozen, versioned schema
K1-Jev SHALL answer only the question templates defined in `kaine/decision/schema.py`, whose `SCHEMA_VERSION` SHALL change whenever any question's instructions or options change. A trained model SHALL record the schema version it was trained on. The state SHALL be external speech, with at most the one context field its question's role names (section 1a of the design), and SHALL NEVER contain `think` content or other private cognitive content.

#### Scenario: A schema change is a new version
- **WHEN** a question's instructions or options are edited
- **THEN** `SCHEMA_VERSION` is incremented and a model trained on the old version is not served for the new one

### Requirement: Training data contains no entity data and only licence-clean sources
The data builder SHALL read only local synthetic data, Banking77 (CC-BY-4.0) and MultiNLI's OANC genres at pinned revisions with checked hashes. It SHALL exclude MultiNLI's fiction genre, BoolQ, AG News and SST-5. It SHALL have no input for arbitrary text files and SHALL refuse to run when any configured path lies under the KAINE data root or `state/`. No natural-language example text SHALL be written by a cloud model.

#### Scenario: A path under the data root is refused
- **WHEN** the builder is given an output or cache directory under the KAINE data root
- **THEN** it exits non-zero naming the path and writes nothing

#### Scenario: The fiction genre is absent
- **WHEN** the MultiNLI portion of the training data is built
- **THEN** no example comes from the `fiction` genre

### Requirement: The gold set is operator-labelled, blind and never used for tuning
The held-out gold set SHALL be generated separately from train and dev, SHALL contain at least 40% near-miss items per question, and SHALL be labelled by the operator on a local page that never shows the generated label. Gold labels SHALL NOT be used for training, temperature fitting or threshold selection, and SHALL NOT be committed to the repository.

#### Scenario: The labelling page is blind
- **WHEN** the labelling page serves an item
- **THEN** the response contains neither the generated label nor the item's template or category

### Requirement: The labelling page is reachable only from the local machine with its token
The labelling page SHALL bind to `127.0.0.1` only, SHALL require a random per-run token on every request, SHALL reject a `Host` header other than its own loopback address and port, and SHALL load no external resources.

#### Scenario: A request without the token is refused
- **WHEN** a request reaches the page without the run's token
- **THEN** it receives 403 and no item or label is returned

#### Scenario: A non-loopback bind is refused
- **WHEN** the page is started with a bind address other than `127.0.0.1`
- **THEN** it exits non-zero without listening

### Requirement: Training never runs beside a live entity
The SFT script SHALL refuse to start while a cognitive cycle is connected to the bus or a `kaine-cycle` container is running, and SHALL run out of process under the trainer interpreter with an explicit argv and no shell.

#### Scenario: Training refuses with a cycle running
- **WHEN** the SFT script starts while a cognitive cycle is connected to the bus
- **THEN** it exits non-zero before loading any weights

### Requirement: Thresholds are recall-first for welfare questions
Per-question `noul` thresholds SHALL be fitted on the development split only. For the welfare questions named in the design, the threshold SHALL be the highest that keeps development recall at or above 0.95; other questions SHALL use the F1-optimal threshold.

#### Scenario: A welfare threshold keeps recall
- **WHEN** thresholds are fitted for `wishes_to_stop`
- **THEN** its development recall at the chosen threshold is at least 0.95

### Requirement: The bake-off winner ships
The system with the highest gold macro-F1 among K1-Jev, the zero-shot decision models, the fine-tuned encoder controls and the deterministic graders SHALL be the one served. When K1-Jev's lead over the best control has a paired-bootstrap 95% interval that includes zero, the smaller or simpler system SHALL ship. The result SHALL be recorded under `docs/records/`.

#### Scenario: A control wins
- **WHEN** a control's gold macro-F1 exceeds K1-Jev's
- **THEN** the control is the served system and K1-Jev is not published

### Requirement: The served prompt is the trained prompt
The exported GGUF SHALL carry `<arch>.decision.type = openjev`, the same `systemone.jinja` used to render training prompts as its `systemone` chat template, and the fitted per-type temperatures. Export acceptance SHALL show that `/v1/systemone` probabilities on the pinned llama-server equal, within 1e-3, the tempered softmax over the option letters' logits for the Python-rendered prompt, on 50 development items.

#### Scenario: Template drift fails export
- **WHEN** llama-server's rendering of the template differs from the training renderer for any parity item
- **THEN** the parity check fails and the export is not accepted

### Requirement: Publication is confirmed and licensed
K1-Jev SHALL be published under Apache-2.0 with a model card stating its schema, data sources and licences, gold metrics with intervals, the bake-off result, and that it reads external speech only. Every upload SHALL be confirmed with the integrator immediately before it happens, and `NOTICE` and the licence appendix SHALL carry entries for every dataset and model used.

#### Scenario: No silent upload
- **WHEN** an upload to HF or Ollama is about to run
- **THEN** it has been confirmed with the integrator for that specific upload

### Requirement: Every state field names its role
From schema v2, the state SHALL be JSON whose utterance key is `speaker_said` and whose context, when the question has one, is under the key for its role: `request`, `trait` or `reference_event`. The state SHALL NOT use a generic `context` key. Training, the served client and the labelling page SHALL use the same roles. The client SHALL send one request per context role, so that every served state has a shape the model was trained on.

#### Scenario: A trait item carries its trait
- **WHEN** a `trait_claim` example is assembled or served
- **THEN** its state holds the trait under `trait` and the utterance under `speaker_said`, and no `context` key

#### Scenario: Mixed questions are split by role
- **WHEN** the client is asked `declined` and `trait_claim` about one utterance
- **THEN** it sends one request whose state carries `request` and another whose state carries `trait`, and neither state carries both

### Requirement: The labelling page shows each field under its role
The labelling page SHALL show an item's context under a label naming its role, before the utterance, which it SHALL show under "The speaker said:". It SHALL render the trait of a `trait_claim` item, and SHALL then show the question, its definition and the options.

#### Scenario: A trait item is answerable
- **WHEN** the page serves a `trait_claim` item
- **THEN** it shows "Trait being asked about:" with the item's trait, then "The speaker said:" with the utterance
