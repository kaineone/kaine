# welfare-monitoring Specification

## Purpose
TBD - created by archiving change welfare-events-to-bus. Update Purpose after archive.
## Requirements
### Requirement: Content-free gray-zone events published to the bus
The welfare observer SHALL publish each detected gray-zone event to the bus as a
`welfare.gray_zone` event (source `welfare`, stream `welfare.out`) IN ADDITION to
its existing JSONL sink write. The published payload SHALL be content-free: it
SHALL contain only the `gray_zone_event` enum label and numeric scalars/counters
computed by the observer, and SHALL NOT contain any field copied from a source
event payload. The published payload SHALL be the same content-free dict written
to the sink.

#### Scenario: A detected gray-zone event is published content-free
- **WHEN** the welfare observer detects any gray-zone condition (replay_overload, unmaintained_fatigue, sustained_extreme_vad, or sustained_interoceptive_distress)
- **THEN** it publishes a `welfare.gray_zone` event on `welfare.out` whose payload carries the `gray_zone_event` label plus numeric scalars only
- **AND** it also writes the same content-free record to its JSONL sink
- **AND** no field from any source event payload appears in the published payload

#### Scenario: A non-numeric source field cannot be smuggled into the published payload
- **WHEN** the observer builds the published payload
- **THEN** only the `gray_zone_event` label and `int`/`float` values are included, and any non-numeric value is dropped

### Requirement: Autonomous protective response acts on repeated gray-zone events of any category
The autonomous welfare-protective response SHALL act on repeated `welfare.gray_zone`
events of ANY of the four categories, not only sustained interoceptive distress.
The cycle-layer welfare-protective monitor SHALL subscribe to `welfare.out`
`welfare.gray_zone` events and feed each into its windowed-repeat arm; when the
count within the configured window crosses the configured threshold, it SHALL take
the configured preserve-then-act protective response. The existing sustained
interoceptive-distress arm (read off `soma.out`) SHALL be retained. The coupling
SHALL be bus-only, with no import of `kaine.evaluation` by the cycle-layer monitor.

#### Scenario: Repeated gray-zone events of a non-distress category trigger the response
- **WHEN** `welfare.gray_zone` events of a non-distress category (e.g. replay_overload) recur on `welfare.out` and cross the configured repeat threshold within the window
- **THEN** the welfare-protective monitor preserves the entity first, then takes the configured action (pause/end/notify), and records the welfare action

#### Scenario: The sustained-distress arm still functions
- **WHEN** Soma reports sustained interoceptive distress on `soma.out` crossing the configured duration
- **THEN** the welfare-protective monitor still triggers the preserve-then-act response from that arm

### Requirement: Research log and raw archive capture gray-zone events
The curated research event log SHALL capture `welfare.gray_zone` events by
following `welfare.out`, recording the `gray_zone_event` label plus an EXACT
numeric-field allowlist (not suffix-matching) so a future payload field cannot
smuggle content into the export-eligible log. The local-only raw bus archive SHALL
include `welfare.out` among the streams it archives verbatim.

#### Scenario: The curated log records a gray-zone event with no content
- **WHEN** a `welfare.gray_zone` event is published on `welfare.out`
- **THEN** the curated research log writes a record with `event_type` `welfare.gray_zone`, the `gray_zone_event` label, and only allowlisted numeric fields
- **AND** no content field appears in the record

#### Scenario: A field outside the exact allowlist is dropped from the curated log
- **WHEN** a `welfare.gray_zone` payload carries a field not in the exact numeric allowlist
- **THEN** that field is not written to the curated research record

### Requirement: The welfare-protective monitor applies a boot cold-start warm-up

The cycle-layer welfare-protective monitor SHALL apply a configured cold-start
warm-up (`[preservation.welfare_response].warmup_s`) after the run starts. During
the warm-up window, `welfare.gray_zone` and sustained-distress events SHALL be
observed and logged but SHALL NOT count toward the windowed-repeat threshold or
trigger the preserve-then-act response. This prevents boot transients — distress
reported before homeostatic setpoints settle — from being mistaken for sustained
welfare problems. After the warm-up window, both the windowed-repeat arm and the
sustained-distress arm function unchanged; genuine sustained distress re-accrues
immediately once warm-up ends.

#### Scenario: Boot-transient distress within warm-up does not trigger a response

- **WHEN** gray-zone or distress events occur within the configured `warmup_s`
  after run start
- **THEN** they are logged but do not count toward the repeat threshold and no
  preserve-then-act response is taken

#### Scenario: Sustained distress after warm-up still triggers the response

- **WHEN** the warm-up window has elapsed and repeated gray-zone events cross the
  configured threshold within the window (or Soma reports sustained distress)
- **THEN** the monitor preserves the entity first, then takes the configured
  action, as before

