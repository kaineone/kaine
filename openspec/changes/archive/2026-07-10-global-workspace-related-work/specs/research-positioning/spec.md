# research-positioning

## ADDED Requirements

### Requirement: The paper cites the emergent LLM workspace without conflating it with KAINE's

The paper SHALL cite the emergent-global-workspace result in language models
(Gurnee et al. 2026) as related work motivating the workspace frame, and SHALL, in
the same context, distinguish that emergent intra-model workspace from KAINE's
explicit architectural workspace across modules (Syneidesis). The citation SHALL
NOT be presented as empirical validation of KAINE's architecture.

#### Scenario: The citation is accompanied by the distinction

- **WHEN** the paper cites the emergent-workspace result
- **THEN** the same passage states that it is an emergent intra-model phenomenon,
  distinct from KAINE's explicit architectural workspace, and does not claim it
  validates KAINE's design

#### Scenario: No bare "see also"

- **WHEN** the emergent-workspace result is referenced
- **THEN** it appears as motivation/related work with the distinction stated, not
  as an unqualified endorsement of the architecture
