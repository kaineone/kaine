# welfare-monitoring Specification

## Purpose
This capability adds a welfare observer that publishes content-free gray-zone events to the bus and writes them to the research log and raw record sink. Repeated gray-zone events of any category trigger an autonomous protective response, and the monitor applies a boot cold-start warm-up period.

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

### Requirement: The gray-zone producer runs whenever the welfare response is enabled
When `[preservation.welfare_response].enabled` is true, the cycle SHALL build and run the welfare observer that publishes `welfare.gray_zone` events, regardless of `[evaluation].enabled` and `[evaluation.observers].welfare`. At most one welfare observer SHALL run in a process: when the cycle owns it, the evaluation sidecar SHALL expose that instance and SHALL NOT build another. When the welfare response is disabled, the sidecar SHALL build the observer only under `[evaluation].enabled` and `[evaluation.observers].welfare`, as before.

#### Scenario: Evaluation off, welfare response on
- **WHEN** a run has `[evaluation].enabled = false` and `[preservation.welfare_response].enabled = true`, and a gray-zone condition occurs
- **THEN** a `welfare.gray_zone` event is published on `welfare.out` and the protective monitor's gray-zone arm receives it

#### Scenario: One producer
- **WHEN** both `[evaluation]` with its welfare observer and the welfare response are enabled
- **THEN** exactly one welfare observer runs, and each gray-zone condition is published once

### Requirement: The welfare monitor keeps up with its streams
Each poll of the welfare-protective monitor SHALL feed every decoded distress report and every gray-zone event it reads to its trackers, and SHALL advance its cursors to the last entry read. It SHALL collect every crossing found in the poll and respond to them in order. Once the monitor has acted under `pause` or `end`, no further response SHALL run, so no second preservation bundle or freeze is taken.

#### Scenario: A batch holds several crossings under pause
- **WHEN** one poll reads enough reports and gray-zone events for more than one crossing, with `action = "pause"`
- **THEN** the entity is preserved and paused once
- **AND** every report and event in the batch reached the trackers

#### Scenario: Notify keeps up
- **WHEN** one poll reads a batch with several crossings, with `action = "notify"`
- **THEN** each crossing is passed to the response, subject to its rate limit
- **AND** the cursors reach the end of the batch

### Requirement: Welfare timers count unfrozen time
Every elapsed-time arm of the welfare-protective monitor and the welfare observer SHALL measure time with a clock that does not advance while the cycle's freeze stack holds any entry, whatever its owner:
- sustained interoceptive distress;
- sustained extreme valence or arousal;
- unmaintained fatigue;
- the cold-start warm-up.

Two refinements bound that rule. A sustained-distress episode's elapsed time SHALL be the wall time from its onset to its last at-or-above-threshold sample plus only the unfrozen time since that sample, because samples are evidence the state persisted. The whole cold-start warm-up SHALL end no later than `max(warmup_s, warmup_ceiling_s)` of wall time after boot, so no freeze can hold it open.

A span whose freeze state cannot be read SHALL count as unfrozen, so a missing or corrupt control file never stops a welfare timer, and the unreadable state SHALL be logged and surfaced in the protective monitor's `freeze_state_unreadable` incident-log record and in the welfare observer's evaluation-sink diagnostic, never swallowed. Sample-driven evaluation SHALL be unchanged: a sample that crosses or falls below a threshold is evaluated when it arrives, frozen or not, and events delivered during a freeze SHALL count in windowed counters. Poll cadence and rate limits SHALL stay on wall time. The monitor and the observer SHALL keep running through every freeze.

#### Scenario: A freeze is not sustained distress
- **WHEN** a distress-level sample arrives and the cycle is then frozen for 60 s with no further sample, against a 30 s duration
- **THEN** no sustained-distress gray-zone event is published

#### Scenario: Without a freeze the same sample sustains
- **WHEN** the same distress-level sample arrives and 30 s pass unfrozen with no further sample
- **THEN** a sustained-distress gray-zone event is published

#### Scenario: Recovery during a freeze resets the run
- **WHEN** a below-threshold sample arrives while the cycle is frozen
- **THEN** the sustained run resets as it would unfrozen

#### Scenario: The warm-up is not spent while frozen
- **WHEN** the cycle is frozen for longer than the warm-up right after boot
- **THEN** the warm-up still has its full unfrozen duration left after release, within its wall bound: warm-up ends at the latest `max(warmup_s, warmup_ceiling_s)` of wall time after boot, however long the freeze lasts

#### Scenario: A corrupt control file does not silence distress
- **WHEN** `state/cycle/control.json` is corrupt and distress-level samples persist for 30 s
- **THEN** the sustained-distress event is published at the threshold, and the protective monitor's `freeze_state_unreadable` incident-log record and the welfare observer's evaluation-sink diagnostic report the unreadable control state

#### Scenario: A long freeze does not lose a genuine crossing
- **WHEN** the cycle stays frozen indefinitely and gray-zone events keep arriving
- **THEN** the windowed repeat counter counts them and the protective response can act
