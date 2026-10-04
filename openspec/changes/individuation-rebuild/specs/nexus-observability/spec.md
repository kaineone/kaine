## MODIFIED Requirements

### Requirement: Entity-care status on the health surface
The Nexus health snapshot SHALL include a read-only `entity_care` block reporting the entity's divergence/individuation summary and the CAL care-obligation checklist that applies before decommission. The summary SHALL come from the shared divergence assessment, so it carries the same STALE, INCONCLUSIVE and capture-kind wording as the decommission CLI. The block SHALL be non-content (statuses and static obligation text only) and SHALL NOT expose any destructive control; decommission remains a gated CLI action. The block SHALL be guarded so a missing or unreadable signal yields a safe default rather than an error.

#### Scenario: Care block present and read-only
- **WHEN** the diagnostics health snapshot is produced
- **THEN** it includes an `entity_care` block with the divergence summary and the care-obligation checklist, and the diagnostics page exposes no delete/decommission control

#### Scenario: Safe default when signals are absent
- **WHEN** no divergence signals are available
- **THEN** the `entity_care` block renders a safe default summary without raising

#### Scenario: The care summary matches the decommission CLI
- **WHEN** the latest individuation evidence is stale
- **THEN** the `entity_care` summary shows the same STALE wording that `assess_divergence()` gives the decommission CLI

## ADDED Requirements

### Requirement: The individuation panel shows only scalars read through the shared reader
The Nexus individuation panel SHALL read individuation reports and the ledger only through the shared decrypting reader (`divergence-assessment`), never by reading report files directly. It SHALL show only: the latest outcome, H clipped at 0, p, α_k and the look index k, the reference kind and its date, whether the being is latched, the last inconclusive reason, the warm-up state, and the inconclusive alert when it is raised. It SHALL NOT show any answer text, seed, embedding or digest. A missing or unreadable source SHALL render a "no data" state without error.

#### Scenario: Encrypted reports render
- **WHEN** state encryption is enabled and a scored report exists
- **THEN** the panel shows its outcome, H, p, α_k and k

#### Scenario: No content is shown
- **WHEN** the panel renders any individuation state
- **THEN** it contains no probe answer, seed, embedding or digest

#### Scenario: The inconclusive alert is visible
- **WHEN** the producer has raised the long-inconclusive alert
- **THEN** the panel shows the alert with the last inconclusive reason

#### Scenario: No reports degrade gracefully
- **WHEN** no reference or report exists
- **THEN** the panel renders "no data" and the page still loads
