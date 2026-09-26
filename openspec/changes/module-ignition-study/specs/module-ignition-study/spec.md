## ADDED Requirements

### Requirement: The study separates each faculty's effect from familiarity
The study SHALL run a main line that gains one faculty per viewing and a control line that re-watches the same programme the same number of times without gaining faculties, both revived from the same post-gestation preservation, and SHALL report each step's ignition measures as main-versus-control differences.

#### Scenario: A step's effect is reported against its control
- **WHEN** step k of the main line and step k of the control line have both viewed the programme
- **THEN** the analysis reports step k's ignition measures as the main line's values minus the control line's

### Requirement: Study lines never share state
Each study line SHALL run with its own state root, its own memory collections and its own bus database, so that no preserved being's state is ever read by or written into the other line.

#### Scenario: Two beings stay separate
- **WHEN** the main and control lines run one after the other on one host
- **THEN** neither line's memories, stage, self-model or bus streams appear in the other's

### Requirement: The study creates and keeps its beings
The study SHALL preserve each being at the end of every viewing and SHALL never delete a preserved being; each step's module set, preservations and logs SHALL be recorded in a step manifest.

#### Scenario: Every viewing ends preserved
- **WHEN** a viewing's programme ends
- **THEN** the being is frozen and preserved, and the step manifest names its preservation
