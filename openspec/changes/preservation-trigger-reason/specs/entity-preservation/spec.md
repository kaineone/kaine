## ADDED Requirements

### Requirement: A divergence preservation names the arm that triggered it
When the divergence monitor preserves the entity on a rising edge, the reason it passes to `preserve_live` and the `reason` of its `preservation.preserved` and `preservation.failed` records SHALL be the new arms of that edge, sorted and joined with `+`. When the verdict is diverged with no named arm, the reason SHALL be `diverged`. The monitor SHALL NOT record the reason `individuation` unless the individuation arm is among the new arms.

#### Scenario: The voice arm fires alone
- **WHEN** the verdict gains only the `voice` arm and the monitor preserves the entity
- **THEN** `preserve_live` receives the reason `voice` and the `preservation.preserved` record has `reason` `voice`

#### Scenario: Two arms fire in one poll
- **WHEN** the verdict gains the `voice` and `consolidation` arms in the same poll
- **THEN** the reason is `consolidation+voice`

#### Scenario: A failed preservation names the arm
- **WHEN** the verdict gains the `consolidation` arm and `preserve_live` raises
- **THEN** the `preservation.failed` record has `reason` `consolidation`
