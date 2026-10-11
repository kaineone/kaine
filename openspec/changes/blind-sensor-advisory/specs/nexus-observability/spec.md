## MODIFIED Requirements

### Requirement: Live welfare status on the entity-care panel
The Nexus dashboard SHALL surface a compact numeric welfare-counter row —
unmaintained-fatigue crossings, sustained-VAD episodes, replay overload, and
sustained interoceptive distress — on the diagnostics entity-care panel, sourced
from the same aggregation as the evaluation tab. The row SHALL be numeric only
and carry no entity-interior content. Below it, the panel SHALL show the number of
blind-sensor advisories raised and the labels of the processors whose advisory is
raised and not yet cleared, read from the welfare rollup; only known processor
labels SHALL be shown, and the panel SHALL state that a blind sensor is a sensor
fault on which no protective action follows.

#### Scenario: Welfare counters render on the entity-care panel
- **WHEN** welfare counters are available (live registry or JSONL rollup)
- **THEN** the entity-care panel shows the four numeric counters

#### Scenario: Welfare counters absent degrade gracefully
- **WHEN** no welfare data is available
- **THEN** the row renders an empty/none state and the page still loads

#### Scenario: A blind processor is listed until it clears
- **WHEN** the rollup holds advisories for `topos` and `soma` and a clear for `topos`
- **THEN** the panel lists `soma` as blind now and shows two advisories raised
