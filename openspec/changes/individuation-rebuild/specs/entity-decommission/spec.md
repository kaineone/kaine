## MODIFIED Requirements

### Requirement: Divergence assessment for decommission
The system SHALL provide `assess_divergence()` that determines whether an entity has individuated through the shared decision function (`divergence-assessment`). Individuation SHALL be keyed on the individuation instrument's result against the being's own reference: the being is individuated when the ledger is latched or the latest fresh scored report has `significant == true`. The assessment SHALL also mark the being diverged on the secondary identity signals (consolidation divergence over threshold, Eidolon `drift_count` and `identity_history`, presence of trained voice adapters). It SHALL NOT key on A/B divergence-from-pretrained, which measures architecture conditioning rather than individuation. The assessment SHALL be read-only, SHALL NOT raise, and when it cannot confirm SHALL advise treating the entity as mature.

The summary SHALL state the individuation evidence honestly:

- **STALE** when the being has changed since the last scored look or the report is older than `max_report_age_s`;
- **INCONCLUSIVE** when the latest run produced no score, with its reason;
- for a `capture` reference, "drift since <captured_at>; drift before that date is not measured by this instrument", and that a non-individuated reading does not mean the being never individuated;
- for a `reconstructed` reference, that the reference was reconstructed with operator approval.

Each of these summaries SHALL include the advice to treat the being as mature if unsure whenever the verdict is not individuated.

#### Scenario: A latched being marks diverged
- **WHEN** the individuation ledger is latched
- **THEN** `assess_divergence()` returns `diverged == true`

#### Scenario: Significant individuation marks diverged
- **WHEN** the latest scored report for the current reference is fresh and has `significant == true`
- **THEN** `assess_divergence()` returns `diverged == true`

#### Scenario: No identity signals reads as not diverged
- **WHEN** no individuation report exists, there is no latch, drift is zero, consolidation divergence is below threshold and there are no trained adapters
- **THEN** `assess_divergence()` returns `diverged == false` with a summary noting it could not be confirmed and to treat the entity as mature if unsure

#### Scenario: A stale result is labelled stale
- **WHEN** the latest scored report is not significant and the conditioning digest has changed since that look
- **THEN** the summary reads "STALE: the being has changed since the last measurement; treat it as mature if unsure"

#### Scenario: A capture reference is labelled
- **WHEN** the reference has `reference_kind="capture"` and the being is not individuated
- **THEN** the summary says the drift is measured only since the capture date and advises treating the being as mature if unsure

### Requirement: Transferable backup before deletion
Decommission SHALL capture an encrypted, transferable backup of the entity's durable state before any deletion, satisfying CAL Article 4.2(b). The backup SHALL bundle the Eidolon self-model, the Lingua intent log, the Hypnos voice adapters, the latest fork snapshot, the whole `state/individuation/` directory (reference, adapter copy, ledger and reports), and an export (or explicit volume-copy instructions) for the Mnemos and Empatheia Qdrant collections, plus a manifest describing the entity, timestamp, divergence assessment, and contents. If the backup cannot be completed, decommission SHALL abort without deleting anything.

#### Scenario: Backup precedes deletion
- **WHEN** an operator runs the decommission CLI
- **THEN** an encrypted backup bundle with a manifest is written before any state is deleted

#### Scenario: Backup failure aborts
- **WHEN** the backup cannot be completed
- **THEN** no entity state is deleted and the CLI exits non-zero

#### Scenario: Individuation evidence is in the backup
- **WHEN** a being with a reference and a ledger is backed up for decommission
- **THEN** the backup contains its `state/individuation/` directory, and a failure to copy it aborts the decommission without deleting anything
