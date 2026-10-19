# documentation-consistency Specification

## Purpose
This capability keeps the documentation consistent with the first-configuration default: the docs describe the module set an entity runs with when no other profile is selected, and say where a host's own choices replace it.

## Requirements

### Requirement: Documentation reflects the first-configuration default

The user-facing documentation SHALL describe the first configuration (the five
predictive-workspace processors, observed-not-conversed, perception as prediction
error, self-initiated voice, reference stimulus corpus, and the workspace-mediation
ablation as the falsifier) as the project's default configuration, with the richer
faculties presented as built-and-gated. Where documentation, code, or the README
disagree with the specs of record, the specs win; the documentation SHALL be brought
into line with them, not the reverse.

#### Scenario: Front-door docs lead with the first configuration

- **WHEN** a reader opens the README or the front-door docs (getting-started,
  for-researchers, architecture, configuration, reproducing-results)
- **THEN** they describe the first-configuration five-processor default, the observed
  (non-chatbot) stance, and the ablation as the primary falsifiable test — not the
  prior "sixteen active modules / conversational" framing

#### Scenario: Terminology matches the reconfiguration

- **WHEN** documentation refers to the live perceptual stimulus
- **THEN** it uses "reference stimulus corpus" (manifest-identified), reserving
  "seeded" for the offline ablation's synthetic streams, and it does not describe the
  retired A/B divergence comparison as a current test

### Requirement: Code comments use the paper's terms
Comments and docstrings in the code and the shipped configuration SHALL describe the workspace in terms of access as the paper of record does, and SHALL NOT describe the system as conscious or ground the access rate in the P3b.

#### Scenario: No consciousness wording in code comments
- **WHEN** the code and shipped configuration are searched for "conscious", "P3b" or "sovereignty"
- **THEN** no comment or docstring describes the system with those terms

### Requirement: Documentation cites the paper by its current title

Where the documentation names the project's research paper, it SHALL use the
paper's current title as the paper's own repository states it.

#### Scenario: The book cites the retitled paper

- **WHEN** a reader looks up which paper the concepts follow
- **THEN** the book names *KAINE: A Modular Cognitive Architecture with a
  Predictive Global Workspace*

### Requirement: Documentation does not describe the project as paused

The documentation, records and change notes SHALL NOT describe the project's development as paused, on hiatus, or waiting on funding.

#### Scenario: A reader opens the README

- **WHEN** a reader opens the repository README or the roadmap appendix
- **THEN** neither says that development is paused or on hiatus
