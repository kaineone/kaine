## MODIFIED Requirements

### Requirement: Live welfare status on the entity-care panel
The dashboard SHALL surface a compact numeric welfare-counter row —
unmaintained-fatigue crossings, sustained-VAD episodes, replay overload, and
sustained interoceptive distress — on the diagnostics entity-care panel, sourced
from the same aggregation as the evaluation tab. The row SHALL be numeric only
and carry no entity-interior content. Below it, the panel SHALL show the number of
blind-sensor and silent-sensor advisories raised since the welfare observer last
started and the labels of the processors that are blind or silent now. Each
processor's state SHALL come from its latest advisory or clear after the latest
reset line in the welfare rollup, read without a line window, decrypting encrypted
lines; only known processor labels SHALL be shown, and the panel SHALL state that
a sensor advisory is a sensor fault on which no protective action follows.

#### Scenario: Welfare counters render on the entity-care panel
- **WHEN** welfare counters are available (live registry or JSONL rollup)
- **THEN** the entity-care panel shows the four numeric counters

#### Scenario: Welfare counters absent degrade gracefully
- **WHEN** no welfare data is available
- **THEN** the row renders an empty/none state and the page still loads

#### Scenario: A blind processor is listed until it clears
- **WHEN** the rollup holds advisories for `topos` and `soma` and a clear for `topos`
- **THEN** the panel lists `soma` as blind now and shows two advisories raised

#### Scenario: A restart clears a stale state
- **WHEN** the rollup holds a blind advisory for `topos`, then a reset line, then a blind advisory for `audition_acoustic`
- **THEN** the panel lists only `audition_acoustic` as blind now

#### Scenario: A long rollup keeps a still-blind processor
- **WHEN** a blind advisory for `soma` is followed by thousands of other rollup lines and no clear for `soma`
- **THEN** the panel still lists `soma` as blind now
