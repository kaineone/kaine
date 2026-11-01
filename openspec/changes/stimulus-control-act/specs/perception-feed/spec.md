## ADDED Requirements

### Requirement: The entity pause holder releases itself
An accepted `pause` command SHALL add the `entity` holder to the playlist clock, and the holder SHALL be released by `resume` or automatically after `P_max` of entity time, whichever comes first. The `entity` holder SHALL combine with other holders as every holder does.

#### Scenario: Automatic release
- **WHEN** the entity pauses the programme and issues no `resume`
- **THEN** the `entity` holder is released after `P_max` and playback continues where it stopped

#### Scenario: A freeze during an entity pause
- **WHEN** a freeze begins during an entity pause and the pause's `P_max` passes first
- **THEN** the clock stays paused until the freeze ends

### Requirement: Seeking wraps within a channel
With stimulus control enabled, `next` and `previous` SHALL move to the start of the adjacent item of the current channel, wrapping from the last item to the first and from the first to the last, and running past a channel's last item SHALL continue at that channel's first item.

#### Scenario: Next on the last item
- **WHEN** the entity issues `next` during the programme's last item with perceived programme time short of the total length
- **THEN** playback moves to the first item and no end-of-programme preservation is requested

### Requirement: The viewing ends at the programme's perceived length
With stimulus control enabled, the viewing SHALL end when perceived programme time, which excludes every paused span, reaches the total length of channel 0, and the end-of-programme preservation SHALL still be requested exactly once per start. Without a seek or a channel switch the shared clock SHALL map time to items exactly as the plain playlist clock does.

#### Scenario: The viewing length is unchanged
- **WHEN** the entity skips items during a viewing
- **THEN** the end-of-programme preservation is requested once, when perceived programme time reaches the programme's total length

### Requirement: Picture and sound follow a jump
When the shared clock's presented position jumps (a seek, a channel switch, or a wrap past a channel's end), the video source SHALL reopen the presented item and seek its decoder to the clock's offset, and the audio producer SHALL resync at the clock as on a restart, emit no block from before the jump, and stay paced against the clock.

#### Scenario: A seek
- **WHEN** the entity's `next` is accepted during the first item
- **THEN** the next frame read and the next PCM heard come from the second item, and the delivered audio position is on the clock's item and offset

### Requirement: Every item is measured before playback
With stimulus control enabled, boot SHALL register every programme item's container duration on the shared clock before playback, and SHALL stop with a stimulus-control error naming the item by index and order, never by path, when an item cannot be measured.

#### Scenario: An item that cannot be measured
- **WHEN** stimulus control is enabled and an item's duration cannot be measured
- **THEN** the boot stops with a stimulus-control error

### Requirement: The programme gain stays within its bound
The audio feed SHALL apply the programme gain set by accepted `louder` and `quieter` commands in steps of `G_step`, within plus or minus `G_max` decibels around the programme level, before the audition module reads the samples. A raised gain SHALL pass a smooth knee rather than clip, at 0 dB the samples SHALL pass unchanged, and the gain SHALL be zero at the start of each viewing.

#### Scenario: A new viewing
- **WHEN** a viewing starts after the entity raised the gain in the previous one
- **THEN** the gain is zero

#### Scenario: Plus 6 dB
- **WHEN** the entity raises the gain three steps of 2 dB on a programme well below full scale
- **THEN** the audition module receives samples about twice the programme's amplitude

### Requirement: Programme channels
With stimulus control enabled, channel 0 SHALL be `[perception_feed].playlist_manifest` and each path in `[stimulus_control].channels` SHALL be a further channel, checksummed and verified like the first. An accepted `channel:<k>` SHALL move to the start of channel `k`'s first item. A channel that cannot be loaded SHALL stop the boot, and the run manifest SHALL record each further channel's digests.

#### Scenario: A switch
- **WHEN** the operator configures two channels and the entity's `channel:1` command is accepted
- **THEN** playback moves to channel 1's first item, and `next` and `previous` wrap within channel 1
