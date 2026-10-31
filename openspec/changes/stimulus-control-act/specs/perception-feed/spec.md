## ADDED Requirements

### Requirement: The entity pause holder releases itself
An accepted `pause` command SHALL add the `entity` holder to the playlist clock, and the holder SHALL be released by `resume` or automatically after `P_max` of entity time, whichever comes first. The `entity` holder SHALL combine with other holders as every holder does.

#### Scenario: Automatic release
- **WHEN** the entity pauses the programme and issues no `resume`
- **THEN** the `entity` holder is released after `P_max` and playback continues where it stopped

#### Scenario: A freeze during an entity pause
- **WHEN** a freeze begins during an entity pause and the pause's `P_max` passes first
- **THEN** the clock stays paused until the freeze ends

### Requirement: Seeking wraps and never ends the viewing
With stimulus control enabled, `next` and `previous` SHALL move to the start of the adjacent item, wrapping from the last item to the first and from the first to the last, and the viewing SHALL end when perceived programme time reaches the programme's total length. The end-of-programme preservation SHALL still be requested exactly once per start.

#### Scenario: Next on the last item
- **WHEN** the entity issues `next` during the programme's last item with perceived programme time short of the total length
- **THEN** playback moves to the first item and no end-of-programme preservation is requested

#### Scenario: The viewing length is unchanged
- **WHEN** the entity skips items during a viewing
- **THEN** the end-of-programme preservation is requested when perceived programme time reaches the programme's total length

### Requirement: The programme gain stays within its bound
The audio feed SHALL apply the programme gain set by accepted `louder` and `quieter` commands in steps of `G_step`, clipped to plus or minus `G_max` decibels around the programme level, before the audition module reads the samples, and the gain SHALL return to zero at the start of each viewing.

#### Scenario: A new viewing
- **WHEN** a viewing starts after the entity raised the gain in the previous one
- **THEN** the gain is zero
