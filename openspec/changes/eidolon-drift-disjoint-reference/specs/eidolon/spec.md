## MODIFIED Requirements

### Requirement: Workspace broadcasts update the drift detector
Eidolon SHALL subscribe to `workspace.broadcast` and update its
`DriftDetector` with each observed broadcast. The default
`SourceDistributionDrift` SHALL track a recent window of event-source
frequencies (default 100 broadcasts), a reference histogram of the
broadcasts that have left the recent window, and the all-time event count.
The drift score SHALL compare the recent histogram with the reference
histogram, and SHALL be 0.0 until the reference holds at least as many
broadcasts as the window.

#### Scenario: Recent window respects size cap
- **WHEN** 150 broadcasts have been observed with default window 100
- **THEN** the recent histogram counts the last 100 only, the reference
  histogram counts the first 50, and the all-time count covers all 150

#### Scenario: No score before the reference fills
- **WHEN** 150 broadcasts have been observed with default window 100
- **THEN** the drift score is 0.0, because the reference holds fewer than 100 broadcasts

#### Scenario: A shift confined to the window is not diluted by itself
- **WHEN** the source mix of the last window differs from that of every earlier broadcast
- **THEN** the score compares the window with the earlier broadcasts only, and is at least the score the all-time comparison would give
