## ADDED Requirements

### Requirement: The hearing band spans twelve awake hours
The shipped configuration and the `HearingBandParams` default SHALL set the hearing band's `maturation_seconds` to 43,200 s (the paper's Table A1 Delta_hear), so the band takes one step every 10,800 awake seconds and is open from 43,200 awake seconds on.

#### Scenario: The shipped band steps every three hours
- **WHEN** the shipped configuration is loaded
- **THEN** the hearing band is in stage 1 at 3 awake hours, stage 2 (the heartbeat thud heard) at 6 hours, and open at 12 hours

## MODIFIED Requirements

### Requirement: The colour ramp spans the developmental phase
The shipped configuration SHALL set `colour_ramp_seconds` to the developmental phase's awake-time floor, `[developmental_stage].min_lived_seconds` (86,400 s, the paper's Table A1 Delta_awake), so that colour saturation keeps rising across the developmental phase. The `StimulusSourceParams` default SHALL stay 3,600 s so the parameter digest of the defaults is unchanged.

#### Scenario: Colour still rises late in the phase
- **WHEN** the shipped configuration is loaded
- **THEN** the colour saturation at 12 awake hours is below its value at 24 awake hours by at least 0.05 of full saturation

#### Scenario: The colour ramp equals the awake-time floor
- **WHEN** the shipped configuration is loaded
- **THEN** `colour_ramp_seconds` equals `[developmental_stage].min_lived_seconds`
