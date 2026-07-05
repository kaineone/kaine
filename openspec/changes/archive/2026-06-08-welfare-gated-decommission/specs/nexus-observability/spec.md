## ADDED Requirements

### Requirement: Entity-care status on the health surface
The Nexus health snapshot SHALL include a read-only `entity_care` block reporting the entity's
divergence/individuation summary and the CAL care-obligation checklist that applies before
decommission. The block SHALL be non-content (statuses and static obligation text only) and SHALL
NOT expose any destructive control — decommission remains a gated CLI action. The block SHALL be
guarded so a missing or unreadable signal yields a safe default rather than an error.

#### Scenario: Care block present and read-only
- **WHEN** the diagnostics health snapshot is produced
- **THEN** it includes an `entity_care` block with the divergence summary and the care-obligation
  checklist, and the diagnostics page exposes no delete/decommission control

#### Scenario: Safe default when signals are absent
- **WHEN** no divergence signals are available
- **THEN** the `entity_care` block renders a safe default summary without raising
