## MODIFIED Requirements

### Requirement: Precision-weighted salience is a four-factor product

Syneidesis SHALL compute each event's salience as the product of four factors —
`intensity × novelty × goal × thymos` — in the live cognitive cycle, matching the
paper's selection criterion (§3.2, §3.4.3). The `thymos` factor SHALL be derived
from the entity's current affect state (arousal/valence), and the `goal` factor,
when active, SHALL be derived from the event's relevance to the entity's current
drives and preferred states.

The `thymos` factor SHALL default to the real affect-derived source (the
arousal-weighted `StateModulator`) and SHALL NOT default to the constant
placeholder. Selecting the `static` fallback for the `thymos` factor is a
deliberate downgrade from its shipped default and SHALL emit a degraded-mode
warning.

The `goal` factor MAY default to the constant `static` baseline as a documented
STAGED rollout pending validation of the drive-relevance mapping on logged runs.
Because `static` is the goal factor's intended shipped state — not an operator
downgrade — that staged default SHALL NOT emit a degraded-mode warning; it MAY be
announced by an informational (non-warning) boot note. Selecting
`drive_relevance` activates the real goal scorer. Should the goal factor's shipped
default later become the real source, selecting `static` SHALL then emit a
degraded-mode warning (the warning fires on a downgrade from the shipped default,
per factor).

The `static` placeholders (`StaticGoalScorer`, `StaticThymosModulator`) MAY remain
available as an explicitly selected dev-only fallback / negative control. A
degraded-mode warning SHALL be emitted only for a factor deliberately downgraded
from a real shipped default to `static`, and SHALL NOT be emitted for a factor
sitting on its shipped default.

The salience computation SHALL remain a pure function of the event and the current
affect/goal state (no wall-clock, no RNG, no new bus publication), preserving the
deterministic-cycle and canonical-ordering guarantees.

#### Scenario: Live salience uses the real affect factor

- **WHEN** an event is scored while the entity is in a high-arousal affect state
- **THEN** its salience reflects the arousal-weighted Thymos factor
- **AND** differs from the value the constant placeholder would have produced

#### Scenario: Shipped defaults emit no degraded-mode warning

- **WHEN** the cycle is assembled with the shipped defaults (Thymos factor real,
  goal factor on the staged static baseline)
- **THEN** no degraded-mode warning is emitted
- **AND** the staged goal factor MAY be announced by an informational boot note

#### Scenario: Goal factor weights drive-relevant events

- **WHEN** the goal factor is activated (`drive_relevance`) and two events with
  equal intensity and novelty are scored, one relevant to the currently-dominant
  drive and one not
- **THEN** the drive-relevant event receives the higher goal factor
- **AND** is ranked at least as high in coalition selection

#### Scenario: Deliberate Thymos downgrade preserves the negative control and warns

- **WHEN** the operator selects the `static` fallback for the Thymos factor (and
  the goal factor is also static)
- **THEN** selection is bit-for-bit identical to the prior two-factor behavior
- **AND** a degraded-mode warning naming the downgraded Thymos factor is emitted
