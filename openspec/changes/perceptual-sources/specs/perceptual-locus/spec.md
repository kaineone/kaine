## ADDED Requirements

### Requirement: The source is the one source of truth and the locus is derived
With the perceptual-source registry on, desired state SHALL persist `source` and a set of off-holders (`sleep`, `freeze`, `operator`) and SHALL NOT persist a locus. The locus SHALL be computed on read: `off` while any off-holder is present, otherwise the selected source's kind-derived class. With the registry off, no `source` or off-holder field SHALL be written.

#### Scenario: Selecting the simulated world
- **WHEN** the simulated world is selected while the webcam was selected
- **THEN** the locus reads `virtual`, and the real camera and microphone have closed before the simulated camera opens

#### Scenario: Sleep and an operator choice
- **WHEN** the webcam is selected while the entity sleeps
- **THEN** the locus stays `off` until the sleep holder is removed, and then reads `physical`

### Requirement: Every desired-state change goes through one locked writer path
Every writer of desired state SHALL use one update function that holds an exclusive cross-process lock across read, change and atomic write. The developmental lock SHALL pin `source` to the programme, and sleep SHALL only add and remove its off-holder.

#### Scenario: Concurrent writers
- **WHEN** sleep adds its holder while the dashboard selects a source
- **THEN** both changes are kept, and the entity does not perceive while asleep

### Requirement: Today's writers move onto the locked path when the registry is on
With the registry on, the developmental lock, sleep, the loss fallback and `POST /diagnostics/perception/locus` SHALL write only through the locked writer path: the developmental lock pins the programme; sleep adds and removes its off-holder; `/locus` with `off` adds the operator off-holder and with `physical` or `virtual` selects that class's configured default source, answering 409 when none is configured.

#### Scenario: The dashboard sets physical with no default
- **WHEN** `/locus` is posted with `physical` and no `default_physical` is configured
- **THEN** the route answers 409 naming the source route, and desired state is unchanged

### Requirement: Every modality is closed while the locus is off
With the registry on, the switching factories' desired readers SHALL return false for every modality while any off-holder is present, whatever the selected source.

#### Scenario: Sleep closes the webcam
- **WHEN** the webcam is selected and sleep adds its off-holder
- **THEN** the camera and microphone close within one poll interval and stay closed until the holder is removed
