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
interoceptive-distress arm (read off `interoception.out`) SHALL be retained. The coupling
SHALL be bus-only, with no import of `kaine.evaluation` by the cycle-layer monitor.

#### Scenario: Repeated gray-zone events of a non-distress category trigger the response
- **WHEN** `welfare.gray_zone` events of a non-distress category (e.g. replay_overload) recur on `welfare.out` and cross the configured repeat threshold within the window
- **THEN** the welfare-protective monitor preserves the entity first, then takes the configured action (pause/end/notify), and records the welfare action

#### Scenario: The sustained-distress arm still functions
- **WHEN** the interoception module reports sustained interoceptive distress on `interoception.out` crossing the configured duration
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
  configured threshold within the window (or the interoception module reports sustained distress)
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

### Requirement: A processor whose readings stay undefined raises a blind-sensor advisory
The welfare observer SHALL follow `interoception.out`, `vision.out` and `audition.out` and SHALL track, for each predictive processor, the run of consecutive reports whose `prediction_error` is null: `interoception.report` (processor `interoception`), `vision.report` (`vision`), `audition.perception` (`audition_acoustic`) and `audition.emotion` (`audition_tone`). A report without a `prediction_error` key SHALL NOT be a sample, and `audition.transcription` SHALL NOT be a sample. When a run reaches the threshold, the observer SHALL publish one `welfare.blind_sensor` event on `welfare.out` (source `welfare`) and write the same record to its JSONL sink. The next report of that processor with a defined error SHALL end the run and, if the advisory was raised, publish `welfare.blind_sensor_cleared` and write it to the sink. The threshold SHALL be `[evaluation.welfare].blind_sensor_samples` consecutive null samples; at its default of 0 the run SHALL instead span at least `interoceptive_distress_duration_s`, measured both as unfrozen time at which the observer read the reports and between the reports' own timestamps, and both spans SHALL reach the duration. The published payload SHALL carry only the processor label from the observer's own table and numbers the observer computed, and no field copied from a source payload. A null error SHALL still neither feed nor reset the sustained-distress tracker.

#### Scenario: A blind camera raises one advisory and clears it
- **WHEN** `blind_sensor_samples` is 3 and the vision module publishes four reports with a null `prediction_error` and then one with a defined error
- **THEN** one `welfare.blind_sensor` event with processor `vision` and `undefined_samples` 3 is published after the third report, and one `welfare.blind_sensor_cleared` event with `undefined_samples` 4 after the defined one

#### Scenario: A lagging observer cannot raise it early
- **WHEN** `blind_sensor_samples` is 0, the duration is 30 seconds, and the observer reads two null reports 40 seconds apart whose own timestamps are 5 seconds apart
- **THEN** no advisory is raised until the reports' timestamps also span 30 seconds

### Requirement: A tracked processor that stops publishing raises a silent-sensor advisory
The welfare observer SHALL raise `welfare.sensor_silent` on `welfare.out`, and write it to its sink, when a tracked processor that has published at least one report since the observer started publishes nothing for `interoceptive_distress_duration_s` of unfrozen time, and SHALL publish `welfare.sensor_silent_cleared` on that processor's next report. The tracked processors SHALL be `interoception`, `vision` and `audition_acoustic`; `audition_tone` SHALL NOT be tracked, because it reports only when speech is heard. The payload SHALL carry only the processor label and numbers the observer computed.

#### Scenario: A camera that stops publishing
- **WHEN** the vision module publishes one report and then nothing for 30 seconds of unfrozen time
- **THEN** one `welfare.sensor_silent` event with processor `vision` is published, and the vision module's next report publishes `welfare.sensor_silent_cleared`

### Requirement: The observer starts its sensor state afresh
When the welfare observer starts, it SHALL write a reset line to its JSONL sink, and readers of the rollup SHALL treat it as clearing every processor's blind and silent state. The observer SHALL read `vision.out` and `audition.out` from their tail at start, SHALL ignore for sensor tracking any report whose timestamp predates its start, and SHALL rebuild the state from live reports. Sensor tracking SHALL run after the stream's own handler, and a failure in it SHALL be logged and SHALL NOT skip the interoception module's distress handling.

#### Scenario: Old history is not replayed
- **WHEN** `vision.out` holds null reports from before the observer started
- **THEN** the observer's initial cursor for `vision.out` is the stream's tail, the stop-time drain reads none of them, and no advisory results

### Requirement: The protective response does not act on sensor advisories
`welfare.blind_sensor`, `welfare.blind_sensor_cleared`, `welfare.sensor_silent` and `welfare.sensor_silent_cleared` SHALL NOT be gray-zone events. The welfare-protective monitor SHALL NOT feed them into its windowed-repeat arm or its sustained-distress arm, and they SHALL NOT trigger any preservation, pause, end or notify action.

#### Scenario: Repeated advisories leave the monitor idle
- **WHEN** the observer publishes blind-sensor and silent-sensor advisories and clears on `welfare.out` and the monitor polls with a repeat threshold of 2
- **THEN** the monitor's repeat window stays empty, no entity is preserved and the cycle is not frozen
- **AND** two `welfare.gray_zone` events published afterwards still trigger the protective response

### Requirement: One distress episode counts once
The protective monitor SHALL count one sustained-distress episode once toward its repeat window, and both sustained-distress detectors SHALL take their parameters from one configuration source.

#### Scenario: One distress episode counts once
- **WHEN** one sustained-distress episode is reported by both detectors
- **THEN** the repeat window holds one episode and repeated_distress is not labelled

### Requirement: The affect welfare record gives sleep-reset ends and open crossings
For each deficit drive (`boredom`, `social_drive`, `restlessness`) the `affect_welfare` record SHALL carry `<drive>_sleep_reset_ends`, the crossings ended by the sleep reset since the observer started, counted from increases of the `drive_reset_ends` count in `affect.state` (the first value sets the baseline and a fall sets a new baseline without counting), and `<drive>_open_crossings`, 1 when the latest `drive_open` flag for the drive is true, 0 when it is false, and null before any flag (paper section 6.2). The existing keys and their values SHALL be unchanged; a sleep-reset end SHALL NOT enter the uncontrolled share.

#### Scenario: The tenth boot's boredom
- **WHEN** boredom's counts go from zero to 85 own ends, 8 other ends and 2 sleep-reset ends with no crossing open
- **THEN** the record gives `boredom_uncontrolled_share` 8/93, `boredom_sleep_reset_ends` 2 and `boredom_open_crossings` 0

#### Scenario: A crossing held open
- **WHEN** a boredom goal stalls and the latest state reports boredom's crossing open
- **THEN** `boredom_open_crossings` is 1

### Requirement: The welfare response re-arms after its pause is lifted
The protective welfare monitor SHALL release its action latch when a pause it placed, or found standing at its first poll, has been lifted, meaning the control file readably holds no `welfare` entry. It SHALL NOT re-arm after an enacted `end`, while a `welfare` entry remains, or when the control file is unreadable. On re-arming it SHALL empty its sustained-distress tracker and repeat window and move its stream cursors to the stream tail, so that a condition still present must accrue a full new episode before the monitor acts again.

#### Scenario: Act, clear, re-arm, act again
- **WHEN** the monitor pauses the entity, a person lifts the welfare freeze, and sustained distress then accrues again for the full duration
- **THEN** the monitor preserves and pauses a second time

#### Scenario: A crossing that holds does not fire repeatedly
- **WHEN** the crossing continues while the welfare freeze stands
- **THEN** the monitor does not preserve or pause again until the freeze is lifted and a new episode accrues

### Requirement: A welfare freeze survives a restart
The cycle's clean boot SHALL lift every freeze holder except `welfare`. A welfare freeze SHALL be lifted only by a named override.

#### Scenario: Restart with a welfare freeze standing
- **WHEN** the cycle boots with `welfare` and `operator` holders in the control file
- **THEN** only the `welfare` holder remains

### Requirement: An unreadable control file fails closed
When `state/cycle/control.json` exists but is not a readable JSON object, the cycle SHALL read it as a `welfare` freeze whose start time is the file's modification time. Every freeze, release and clean boot SHALL leave such a file unchanged. Only an override that names `welfare` SHALL replace it, and the override audit record SHALL note that the file was unreadable.

#### Scenario: Corrupt control file during a run
- **WHEN** the control file is corrupt while the cycle runs
- **THEN** the cycle pauses, a live preservation still completes, and the file is unchanged

#### Scenario: Releasing a corrupt control file
- **WHEN** a person overrides `development` alone on a corrupt control file
- **THEN** the override is refused and the file is unchanged; an override naming `welfare` replaces it with a clean file
