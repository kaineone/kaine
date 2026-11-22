## MODIFIED Requirements

### Requirement: Optional local-only raw archive behind attestation

The system SHALL provide a `RawBusArchiveConsumer` that archives bus events to `state/research/raw_bus_archive/`, verbatim except for the latent fields: every key in `LATENT_FIELDS` (the perceptual vector fields and `latent_derived`) SHALL be removed at any depth before a record is written, by the sink's latent strip. This archive SHALL be gated behind
BOTH `[research_event_log.raw_archive] enabled = true` AND both attestation
flags (`entity_privacy_attested = true`, `bystander_consent_attested = true`)
set explicitly in config.

The raw archive SHALL be written to a path outside `data/evaluation/` so it
is structurally impossible for the metrics bundle builder to include it.

The raw archive SHALL be encrypted at rest (same `AsyncJsonlSink` +
`StateEncryptor` mechanism as the curated log).

If the attestation flags are not both `true`, `RawBusArchiveConsumer.start()`
SHALL raise `RawArchiveAttestationError` and log at `ERROR` level. The consumer
SHALL NOT start in this state.

The raw archive is never export-eligible. This SHALL be stated explicitly in the
module docstring of `raw_bus_archive_consumer.py`, together with the statement that latent fields are never archived.

#### Scenario: Raw archive is disabled by default

- **WHEN** `config/kaine.toml` is unmodified (shipped state)
- **THEN** `RawArchiveConfig.enabled` SHALL be `false`
- **AND** `RawBusArchiveConsumer` SHALL NOT be constructed or started

#### Scenario: Raw archive refuses to start without both attestations

- **WHEN** `[research_event_log.raw_archive] enabled = true`
- **AND** `entity_privacy_attested = false` (regardless of bystander flag)
- **THEN** `RawBusArchiveConsumer.start()` SHALL raise `RawArchiveAttestationError`

- **WHEN** `[research_event_log.raw_archive] enabled = true`
- **AND** `bystander_consent_attested = false` (regardless of entity flag)
- **THEN** `RawBusArchiveConsumer.start()` SHALL raise `RawArchiveAttestationError`

#### Scenario: Raw archive starts with full attestation

- **WHEN** `[research_event_log.raw_archive] enabled = true`
- **AND** `entity_privacy_attested = true`
- **AND** `bystander_consent_attested = true`
- **THEN** `RawBusArchiveConsumer` SHALL start and write event records
  to the configured archive directory, verbatim except for the latent fields

#### Scenario: Raw archive holds no latent

- **WHEN** the attested archive records a `vision.report` carrying `latent`, `peripheral` and `foveal`, and a broadcast whose metadata carries `latent_derived`
- **THEN** the archived records hold none of those keys and keep every other field

#### Scenario: Raw archive is never included in a metrics bundle

- **WHEN** `build_research_bundle(tier="metrics")` is called
- **AND** `state/research/raw_bus_archive/` contains files
- **THEN** NO file from `state/research/raw_bus_archive/` SHALL appear in the
  bundle (the metrics-tier loop only reads from `data/evaluation/`)

### Requirement: The diagnostics privacy filter removes numeric vectors
The diagnostics privacy filter SHALL remove, at every nesting depth, every field named in its vector-field set (`latent`, `peripheral`, `foveal`, `temporal_context`, `feature_vector`, `latent_derived`) and every list or tuple of 16 or more numbers (booleans excluded) whose key is not a reviewed non-embedding key (`saliences`, `step_magnitudes`). It SHALL do so in dev-content mode as well. No perceptual or latent embedding and no latent-derived value SHALL reach the dashboard stream, the dashboard record or any other surface that uses the filter.

#### Scenario: A vision report
- **WHEN** a `vision.report` carrying `latent`, `peripheral` and `foveal` passes the filter
- **THEN** all three are removed and its scalar fields, `fovea` and `predicted_fovea` are kept

#### Scenario: A short test latent
- **WHEN** a payload carries `latent` with four numbers
- **THEN** it is removed

#### Scenario: An unnamed embedding
- **WHEN** a payload carries a field `embedding_x` holding 64 numbers
- **THEN** it is removed

#### Scenario: A short latent-derived mapping
- **WHEN** a broadcast's metadata carries `latent_derived` holding an 8-number code, and the filter runs in dev-content mode
- **THEN** the `latent_derived` mapping is removed

#### Scenario: Small and reviewed lists survive
- **WHEN** a payload carries `scores` with 5 numbers and `saliences` with 40 numbers
- **THEN** both are kept
