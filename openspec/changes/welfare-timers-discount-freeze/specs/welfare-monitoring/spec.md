## ADDED Requirements

### Requirement: Welfare timers count unfrozen time
Every elapsed-time arm of the welfare-protective monitor and the welfare observer SHALL measure time with a clock that does not advance while the cycle's freeze stack holds any entry, whatever its owner:
- sustained interoceptive distress;
- sustained extreme valence or arousal;
- unmaintained fatigue;
- the cold-start warm-up.

A span whose freeze state cannot be read SHALL count as unfrozen, so a missing or corrupt control file never stops a welfare timer, and the unreadable state SHALL be logged and surfaced in the detector's status, never swallowed. Sample-driven evaluation SHALL be unchanged: a sample that crosses or falls below a threshold is evaluated when it arrives, frozen or not, and events delivered during a freeze SHALL count in windowed counters. Poll cadence and rate limits SHALL stay on wall time. The monitor and the observer SHALL keep running through every freeze.

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
- **THEN** the warm-up still has its full unfrozen duration left after release

#### Scenario: A corrupt control file does not silence distress
- **WHEN** `state/cycle/control.json` is corrupt and distress-level samples persist for 30 s
- **THEN** the sustained-distress event is published at the threshold, and the detector's status reports the unreadable control state

#### Scenario: A long freeze does not lose a genuine crossing
- **WHEN** the cycle stays frozen indefinitely and gray-zone events keep arriving
- **THEN** the windowed repeat counter counts them and the protective response can act

