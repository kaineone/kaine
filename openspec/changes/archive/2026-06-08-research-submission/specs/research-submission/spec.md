## ADDED Requirements

### Requirement: Opt-in, operator-initiated research submission
Research submission SHALL be disabled by default and SHALL never transmit automatically. The
`[research_submission]` config SHALL ship `enabled = false` with an empty recipient. Any submission
SHALL be operator-initiated via the CLI and SHALL present a content preview (the field inventory and
counts) before any network call, then require explicit operator confirmation. The recipient SHALL be
configurable with `kaine.one@tuta.com` suggested in documentation/commented config, and SHALL NOT be
a hardcoded-silent destination.

#### Scenario: Disabled and inert by default
- **WHEN** `config/kaine.toml` is loaded as shipped
- **THEN** `[research_submission].enabled` is `false` and `recipient` is empty, and nothing is
  transmitted

#### Scenario: Preview precedes any send
- **WHEN** the operator runs the submission CLI
- **THEN** the bundle contents are previewed and an explicit confirmation is required before any
  network transmission

#### Scenario: No automatic submission
- **WHEN** the system runs normally
- **THEN** no scheduled or background process transmits research data

### Requirement: Metrics-only bundle by default
The research bundle SHALL contain only numeric/redacted evaluation metrics by default (A/B divergence
scores, individuation results, welfare/gray-zone counts, fatigue, prediction-error, coherence,
nous-policy) plus a manifest enumerating what is included. It SHALL exclude the Lingua intent log,
Mnemos/Qdrant memories, the Eidolon self-model, and conversation content. Including
higher-sensitivity content SHALL require explicit per-field opt-in and a recorded bystander-consent
and entity-privacy attestation, and SHALL still apply redaction.

#### Scenario: Default bundle excludes sensitive content
- **WHEN** a bundle is built with the default tier
- **THEN** it contains numeric metrics + a manifest and contains no `intent_expression.jsonl`, no
  Mnemos memories, no Eidolon self-model, and no conversation text

#### Scenario: Sensitive content is gated
- **WHEN** a higher-sensitivity tier is requested without the required opt-in/attestation
- **THEN** the bundle does not include speech, transcripts, or memories

### Requirement: No unconsented network egress
The system SHALL NOT make unconsented outbound network calls at runtime. The DINOv2 vision encoder
SHALL suppress HuggingFace hub telemetry before loading models. The voice-alignment hot-swap SHALL
reject a non-loopback `reload_endpoint_url` unless `KAINE_ALLOW_NONLOCAL_HOT_SWAP=1` is explicitly
set. Documentation SHALL state that "all-local at runtime" has a single opt-in, operator-initiated
exception (research submission), and SHALL accurately describe the sensitivity of the Lingua intent
log.

#### Scenario: Vision encoder suppresses telemetry
- **WHEN** the DINOv2 encoder loads its model
- **THEN** `HF_HUB_DISABLE_TELEMETRY` is set so no telemetry ping is emitted

#### Scenario: Non-loopback hot-swap endpoint rejected by default
- **WHEN** `reload_endpoint_url` is a non-loopback address and `KAINE_ALLOW_NONLOCAL_HOT_SWAP` is not set
- **THEN** the hot-swap refuses to POST to it
