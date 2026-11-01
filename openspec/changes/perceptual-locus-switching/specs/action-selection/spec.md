## ADDED Requirements

### Requirement: A drive-led switch act after maturation (stage M)
With the switch stage M installed, after the developmental phase, a non-inhibited broadcast whose leading member is the entity's own boredom or restlessness drive event SHALL yield one signed act naming `perceptual_source`, once the arbiter's dwell would pass. Its target SHALL be drawn uniformly, with a run-seeded generator, from the sources the arbiter would accept now. The trigger's basis SHALL be cited at the code site.

#### Scenario: Boredom leads
- **WHEN** the mature entity's boredom drive event leads an accessed broadcast and two sources would be accepted
- **THEN** one switch act is emitted whose target is one of those two

#### Scenario: Nothing to switch to
- **WHEN** no other source would be accepted
- **THEN** no switch act is emitted

### Requirement: Acts on the entity's input are drawn from one set
When both the stimulus-control stage M and the switch stage M are installed, they SHALL be composed into one source that draws once, uniformly over acts, from the union of the stimulus actions the programme can take now and the switch targets the arbiter would accept, and SHALL yield at most one act on the entity's input per broadcast.

#### Scenario: Both installed
- **WHEN** boredom leads a broadcast while the programme is selected, with five stimulus actions and two switch targets available
- **THEN** exactly one act is emitted, drawn from those seven
