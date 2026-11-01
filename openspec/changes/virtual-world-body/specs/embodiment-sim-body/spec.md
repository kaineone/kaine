## ADDED Requirements

### Requirement: A body declares its joints, sensors, rate and stages
An adapter MAY declare a body descriptor: joints with command interfaces (`position`, `velocity`, `effort`), state interfaces and limits; sensors with kind, rate and latency; a control rate; an expected latency; freeze-then-free stages; and whether the operator can reset it. An adapter without a descriptor SHALL behave exactly as before.

#### Scenario: The stub body
- **WHEN** the stub adapter, which declares no body descriptor, is constructed
- **THEN** its channels, stages and gating are unchanged

### Requirement: The MuJoCo adapter models real actuators and timing
The MuJoCo adapter SHALL drive position, velocity or effort actuators with declared gains and force limits, SHALL apply actuator lag and command delay through MuJoCo's actuator dynamics and delay, SHALL apply declared sensor delays, and SHALL step physics at a declared timestep with a control decimation to the body's control rate.

#### Scenario: A commanded step is not instantaneous
- **WHEN** a position command steps by the joint's full range
- **THEN** the joint reaches it only after the declared delay and lag, within its force limit

### Requirement: The adapter injects sensor noise itself
Because MuJoCo stores a sensor's `noise` without applying it, the adapter SHALL add Gaussian noise to each sensor reading at its declared standard deviation, from a generator seeded from the run seed.

#### Scenario: A static joint
- **WHEN** a joint is held still and its sensor declares a non-zero noise
- **THEN** the readings the motor loop receives vary with that standard deviation

### Requirement: Each run samples one randomised world and records it
At boot the adapter SHALL sample masses, damping, friction, actuator gains, delays, sensor noise and scene materials within declared ranges from the run seed, SHALL keep them fixed for the run, and SHALL record the sampled values in the run manifest.

#### Scenario: Two seeds
- **WHEN** two runs use different seeds
- **THEN** their manifests record different sampled parameters, and each run's parameters stay fixed throughout

### Requirement: Command-to-feedback latency is measured and bounded
The adapter SHALL measure the delay from a commanded joint step to the first moved proprioceptive reading at open and every 10 minutes, SHALL record it, and SHALL refuse to open, or close with a named reason, when it exceeds `max_latency_ms` (default 250 ms).

#### Scenario: A slow body
- **WHEN** the measured latency exceeds the bound
- **THEN** the body is not driven, and the reason names the measured value and the bound

### Requirement: A body acts only while its own source is selected
A body paired with a perceptual source SHALL accept actions and setpoints only while that source is selected. While it is not, the world SHALL hold, and an action SHALL return false without effect.

#### Scenario: The programme is selected
- **WHEN** the programme is selected and a setpoint for the simulated head arrives
- **THEN** the simulation is not changed, and no efference copy says `forwarded: true`

### Requirement: Efference says forwarded only when the simulation accepted the command
`apply_setpoints` SHALL write only exposed channels to the simulation, and SHALL return true only when the simulation accepted the command at that step.

#### Scenario: An unexposed channel
- **WHEN** a setpoint names a channel that is not exposed
- **THEN** that channel is not written, and the efference copy does not report it forwarded

### Requirement: No simulated pain or damage without its own design
A simulated body SHALL report touch as contact force and location without valence, and SHALL carry no pain, damage, injury or body-fatigue signal. Adding any such signal SHALL require its own change with cited neuroscience at the code site and an independent second review.

#### Scenario: A hard collision
- **WHEN** a leg strikes an obstacle at its force limit
- **THEN** a touch reading reports the contact, and no aversive or damage signal is produced

### Requirement: The operator can reset a stuck body
A body that declares `reset` SHALL be resettable to its start pose by an operator action, recorded with the operator as its initiator. The entity SHALL have no reset action.

#### Scenario: A fallen base
- **WHEN** the hexapod has tipped over and the operator resets it
- **THEN** the body returns to its start pose, and the record names the operator

### Requirement: The body counts as built only with its driving loop
`embodiment_built()` SHALL be true only when a non-reference body adapter and the motor driving loop are both registered. A MuJoCo body without the driving loop SHALL leave the embodiment module held.

#### Scenario: The simulated JetHexa before the learner
- **WHEN** the simulated JetHexa exists but the driving loop does not
- **THEN** `embodiment_built()` is false and the module cannot join an entity

### Requirement: The default simulated body is a JetHexa model of KAINE's own
The default MuJoCo body SHALL be a JetHexa model written for KAINE: 18 leg joints and a pan-tilt head with a camera, an IMU and joint-position sensors. No file from an unlicensed vendor repository SHALL be vendored. Its model card SHALL mark each physical parameter as provisional, measured or identified.

#### Scenario: The model card
- **WHEN** the provisional model is built from published dimensions
- **THEN** its model card marks the masses and servo gains provisional, and names their sources

### Requirement: The simulated JetHexa matches the real servo bus timing
The JetHexa body SHALL accept position commands with a move time and report joint positions at the control rate the real 115200-baud servo bus supports for 18 joints, with the read delay modelled. Temperature and voltage states SHALL be declared absent in simulation.

#### Scenario: Reading all joints
- **WHEN** the motor loop requests all 18 joint positions
- **THEN** the readings arrive after the modelled bus delay, at the declared rate

### Requirement: Locomotion is learned from joint channels
The JetHexa body SHALL expose joint channels only. The vendor's gait controller SHALL NOT be an entity channel, and any gait generator given to the entity SHALL require its own change with cited neuroscience at the code site.

#### Scenario: The channel list
- **WHEN** the JetHexa body's declared channels are listed
- **THEN** they are joint commands, and no velocity or gait command is among them

### Requirement: The JetHexa curriculum frees the head before the legs
The JetHexa body SHALL declare its stages in this order: head pan; head pan and tilt; one leg's three joints at a time with the other legs held standing; all leg joints. Each stage SHALL be freed only on demonstrated competence.

#### Scenario: Legs stay frozen at first
- **WHEN** the entity is in the first stage
- **THEN** the leg joints are held at their standing pose, and only head pan is driven by the entity
