## ADDED Requirements

### Requirement: A/B divergence meter has a controlled measurement path

The A/B divergence meter SHALL provide a control path that computes divergence
for a controlled `(utterance, workspace-conditioning)` input by running BOTH
arms through the SAME inference path, varying ONLY the workspace conditioning:
the conditioned arm is the utterance under the supplied conditioning, the bare
arm is the SAME utterance under EMPTY conditioning. The control SHALL reuse the
language organ's real conditioning path (Lingua's `ContextAssembler` + the
language-organ chat client, wired at the cycle entrypoint) rather than a
parallel reimplementation, so any divergence it reports is attributable to the
conditioning alone — which is exactly the quantity the meter is defined to
measure. The divergence metric used by the control SHALL be the same metric the
live observer reports (`1 - cosine` of the two embedded outputs), factored into
a single shared definition so the control and observer cannot drift apart.

The control SHALL read approximately zero when the two arms are conditioned
identically (negative control) and large when a known conditioning difference is
injected (positive control). Adding the control SHALL NOT change the behavior of
the live `ABDivergenceObserver`, which continues to sample `lingua.external`
while running.

#### Scenario: Identical/empty conditioning reads ~zero (negative)

- **WHEN** the control runs an utterance with EMPTY workspace conditioning
- **THEN** the conditioned arm and the bare arm receive an identical prompt and
  produce identical output
- **AND** the reported divergence is below a small floor (~0)

#### Scenario: Injected large conditioning reads large (positive)

- **WHEN** the control runs an utterance with a large, known workspace
  conditioning difference injected
- **THEN** the conditioned arm's output differs from the bare arm's output
- **AND** the reported divergence is above a high floor

#### Scenario: The control exercises the real conditioning path

- **WHEN** the real control client is constructed at the cycle entrypoint
- **THEN** it builds the conditioned prompt with Lingua's own `ContextAssembler`
  and runs it through the language-organ chat client
- **AND** empty conditioning reproduces Lingua's "nothing salient" prompt
- **AND** `kaine.evaluation` imports no `kaine.modules.*` code (the coupling is a
  duck-typed seam injected at the entrypoint)

### Requirement: The negative control is a permanent automated test

The negative control SHALL be a permanent, always-on automated unit test: a
phantom signal there (non-zero divergence when the two arms are conditioned
identically) invalidates every divergence result the meter produces, so it must
never be allowed to regress silently. Because identical text embeds to an
identical vector under any embedder, this property is embedder-agnostic and the
permanent test SHALL run with the dependency-free `HashEmbedder` so it needs no
model to execute.

#### Scenario: Negative control runs without a model

- **WHEN** the test suite runs with no sentence-transformer model present
- **THEN** the negative control still executes using `HashEmbedder`
- **AND** asserts divergence below the floor for identically-conditioned arms

#### Scenario: Embedder validity is explicit for the positive control

- **WHEN** the positive control asserts a large divergence
- **THEN** the STRUCTURAL claim (different conditioning → different output →
  divergence above zero) is validated with `HashEmbedder` (always-on, lexical)
- **AND** the SEMANTIC claim (large semantic divergence) is validated with the
  sentence-transformer embedder when the model is available, and is skipped
  rather than faked when the model is absent
