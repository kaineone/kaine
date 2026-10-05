## ADDED Requirements

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
