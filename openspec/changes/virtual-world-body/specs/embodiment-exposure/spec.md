## ADDED Requirements

### Requirement: A body may declare its own channels and ranges
A body with a descriptor SHALL declare its continuous channels as `<joint>.<interface>` with the joint's range, and the core SHALL clamp each channel to the body's declared range. Bodies without a descriptor SHALL keep the canonical channel vocabulary and its ranges.

#### Scenario: A pan joint
- **WHEN** the pan-tilt body declares `pan.position` with range plus and minus 2.6 rad and a setpoint of 4.0 arrives
- **THEN** the core clamps it to 2.6 before the adapter receives it

### Requirement: Declared channels are exposed by a list
For a body with a descriptor, `[embodiment.<adapter>].expose` SHALL list the channel names to expose. A name the body does not declare SHALL refuse boot with a configuration error naming it and the declared channels.

#### Scenario: A misspelled joint
- **WHEN** `expose = ["pna.position"]`
- **THEN** boot refuses, naming `pna.position` and the body's declared channels

### Requirement: Stages come from the body when it declares them
The motor curriculum SHALL use the body's declared freeze-then-free stages when present, and the default stages otherwise.

#### Scenario: The pan-tilt head
- **WHEN** the pan-tilt body declares stages (`pan.position`), then (`pan.position`, `tilt.position`)
- **THEN** the curriculum frees `tilt.position` only after competence on `pan.position`
