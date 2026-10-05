## ADDED Requirements

### Requirement: Documentation reflects the base-thesis default

The user-facing documentation SHALL describe the base-thesis form (the five
predictive-workspace processors, observed-not-conversed, perception as prediction
error, self-initiated voice, reference stimulus corpus, and the workspace-mediation
ablation as the falsifier) as the project's default configuration, with the richer
faculties presented as built-and-gated. Where documentation, code, or the README
disagree with the specs of record, the specs win; the documentation SHALL be brought
into line with them, not the reverse.

#### Scenario: Front-door docs lead with the base-thesis form

- **WHEN** a reader opens the README or the front-door docs (getting-started,
  for-researchers, architecture, configuration, reproducing-results)
- **THEN** they describe the base-thesis five-processor default, the observed
  (non-chatbot) stance, and the ablation as the primary falsifiable test — not the
  prior "sixteen active modules / conversational" framing

#### Scenario: Terminology matches the reconfiguration

- **WHEN** documentation refers to the live perceptual stimulus
- **THEN** it uses "reference stimulus corpus" (manifest-identified), reserving
  "seeded" for the offline ablation's synthetic streams, and it does not describe the
  retired A/B divergence comparison as a current test
