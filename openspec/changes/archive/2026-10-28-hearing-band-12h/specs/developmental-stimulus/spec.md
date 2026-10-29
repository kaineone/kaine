## ADDED Requirements

### Requirement: The hearing band spans twelve awake hours
The shipped configuration and the `HearingBandParams` default SHALL set the hearing band's `maturation_seconds` to 43,200 s (the paper's Table A1 Delta_hear), so the band takes one step every 10,800 awake seconds and is open from 43,200 awake seconds on.

#### Scenario: The shipped band steps every three hours
- **WHEN** the shipped configuration is loaded
- **THEN** the hearing band is in stage 1 at 3 awake hours, stage 2 (the heartbeat thud heard) at 6 hours, and open at 12 hours
