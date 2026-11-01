## ADDED Requirements

### Requirement: Sources are declared as content-free descriptors
With `[perceptual_sources].enabled = true`, boot SHALL build a registry from the `[perceptual_sources.sources.<id>]` tables. Each source SHALL declare an `id`, a `kind`, its modalities with shape and rate, a `locus_class` of `physical` or `virtual`, a `privacy_class`, a `provenance`, `entity_selectable`, and an optional paired `body`. A modality a source does not list SHALL be treated as declared absent.

#### Scenario: A missing modality is declared absent
- **WHEN** a `mujoco` source lists only a `video` modality
- **THEN** its audio modality is declared absent, and the descriptor in the run manifest says so

### Requirement: Invalid source configurations refuse boot
Boot SHALL refuse with a named configuration error on an unknown kind, a missing required field, a duplicate id, an absent initial source, `[perception_feed].mode` set to `live` or `screen` while the registry is on, or a source of privacy class `operator_desktop` marked `entity_selectable`.

#### Scenario: A screen source cannot be made selectable
- **WHEN** a `screen` source is configured with `entity_selectable = true`
- **THEN** boot refuses with a configuration error naming the source and the rule

### Requirement: Off equals absent
With `[perceptual_sources].enabled = false`, which is the shipped value, boot SHALL construct no registry object, no switching factory, no availability poller and no `away` holder, and SHALL write no source field to perception desired state. A seeded, entity-free harness covering the vision and audition capture loops, the playlist feed and the desired-state files SHALL give the same digest as a golden captured on origin/main before this change.

#### Scenario: The shipped configuration
- **WHEN** the registry is off
- **THEN** the harness digest equals the golden, and `state/perceptual_locus/desired.json` has no `source` field

### Requirement: One switching factory per modality follows the selected source
With the registry on, the vision and audition capture loops SHALL each receive one switching factory with the existing factory signature. The factory SHALL open the surface of the selected source. A change of selected source SHALL bump a source epoch, and a capture loop whose open source belongs to an older epoch SHALL close it and open the selected source's surface within one desired-state poll interval. A source whose modality is declared absent SHALL open no surface for that modality.

#### Scenario: From the programme to the webcam
- **WHEN** the selected source changes from the programme to an available device source
- **THEN** within one poll interval the video loop has closed the programme's video source and opened the camera, and the audio loop has opened the microphone

#### Scenario: A source without sound
- **WHEN** the selected source is a `mujoco` source that declares no audio
- **THEN** the audio loop opens no stream while it is selected

### Requirement: The programme waits while the entity is away
While a source other than the programme is selected, the playlist clock SHALL be held by an `away` holder, released when the programme is selected again. The holder SHALL combine with the other holders as every holder does. The viewing's length and its end-of-programme preservation SHALL be unchanged.

#### Scenario: Away and back
- **WHEN** the entity is on the webcam for ten minutes and then returns to the programme
- **THEN** the programme continues where it stopped, and its end-of-programme preservation is requested when perceived programme time reaches its length

### Requirement: A device source opens its devices by identity
A `device` source SHALL identify its camera by a `/dev/v4l/by-id` name or a sysfs-name substring, and its microphone by a sounddevice name substring. An index SHALL be accepted only with `allow_index = true`.

#### Scenario: Re-plugged camera
- **WHEN** the configured camera is unplugged and plugged into another port
- **THEN** the source finds it again by its by-id name, whatever its new node number

### Requirement: A device source accepts only real capture nodes
Discovery SHALL accept only a node whose `VIDIOC_QUERYCAP` device capabilities include video capture. It SHALL refuse a node whose driver is `v4l2 loopback` unless `allow_loopback = true`, in which case the descriptor's provenance SHALL be `recorded`.

#### Scenario: The metadata node is not a camera
- **WHEN** a UVC camera exposes a capture node and a metadata node
- **THEN** discovery binds the capture node and reports the metadata node as `not_capture`

#### Scenario: The OBS virtual camera
- **WHEN** the only video node is a v4l2 loopback and `allow_loopback` is false
- **THEN** the device source is not available, and the reason says it is a loopback

### Requirement: A device source fails closed
Availability SHALL be polled at least every 2 s and SHALL be one of `available`, `absent`, `busy`, `no_access` or `not_capture`. A source that is not `available` SHALL NOT be opened, no other device SHALL be substituted for it, and each refusal message SHALL state what the operator can do.

#### Scenario: The camera is held by another program
- **WHEN** opening the capture node fails with EBUSY
- **THEN** the source is `busy`, nothing is opened, and the message says another program holds the camera

### Requirement: A device source discards the camera's warm-up
On each open, a device source SHALL discard frames until the mean luminance changes by less than 2% between consecutive frames for 5 frames, or until 60 frames have been discarded, and SHALL record the number of discarded frames. No discarded frame SHALL reach the vision module.

#### Scenario: Auto-exposure settling
- **WHEN** the camera's brightness rises over its first 20 frames
- **THEN** the vision module receives its first frame only after the brightness has settled, and the record states how many frames were discarded

### Requirement: Losing the selected source returns the entity to its fallback
When the selected source stays `absent` or `busy` for longer than `[perceptual_sources].loss_grace_s` (default 10 s), the registry SHALL select `[perceptual_sources].fallback` (default the programme) through the operator path, recorded with `by = "source_lost"`, and SHALL publish the change. A returning source SHALL NOT be reselected automatically.

#### Scenario: The webcam is unplugged
- **WHEN** the selected webcam is unplugged and does not return within the grace period
- **THEN** the programme is selected with `by = "source_lost"`, and the welfare observer receives the event

### Requirement: The MuJoCo source renders headless on the planned card
A `mujoco` source SHALL render its body's named camera with `MUJOCO_GL=egl` on the EGL device that matches the configured card by PCI bus id. It SHALL refuse at boot when EGL is unavailable or the mapping does not match, and SHALL NOT fall back to a display-bound backend. Boot SHALL measure the render's memory and time per frame on that card and SHALL refuse past the configured limit.

#### Scenario: No EGL
- **WHEN** EGL cannot be initialised
- **THEN** boot refuses, naming the `mujoco` source and the missing backend

### Requirement: The simulated world steps on entity time and waits while away
The simulated world SHALL step on entity time, and SHALL hold while its source is not selected and while sleep or a freeze holds the clock. The `mujoco` source SHALL declare no audio modality.

#### Scenario: The world waits
- **WHEN** the entity leaves the simulated world for the programme and returns
- **THEN** the simulation time at return equals the simulation time at departure

### Requirement: A declared-absent modality is not a silent sensor
While the selected source declares a modality absent, the welfare observer SHALL NOT raise a silent-sensor advisory for the processor of that modality, and SHALL record the span as `modality_absent` with the source id.

#### Scenario: Silence in the simulation
- **WHEN** the simulated world is selected for longer than the silent-sensor window
- **THEN** no `welfare.sensor_silent` advisory is raised for audition, and the record shows `modality_absent`

### Requirement: Held source kinds are refused until built
A source of kind `stream`, `world` or `scalar` SHALL be refused at boot with a named reason until the change that builds it has merged and its own start conditions hold.

#### Scenario: A stream source today
- **WHEN** a `stream` source is configured
- **THEN** boot refuses and names `virtual-world-body` as the change that builds it

### Requirement: A scalar source becomes a processor with its own forward model
When built, each enabled `scalar` source SHALL be served by one instance of the sensor processor. The instance SHALL have its own forward model sized to the declared channels, normalise its prediction error against its own rolling baseline, and be tracked by the welfare observer's blind-sensor and silent-sensor advisories.

#### Scenario: Two sensors
- **WHEN** a temperature source and a moisture source are enabled
- **THEN** each has its own processor instance, forward model and baseline

### Requirement: A scalar processor reports only real readings
The sensor processor SHALL publish `sensor.report` with the source id, the prediction error, the normalised error and the channel values clipped to their declared ranges. A missing reading SHALL publish no value.

#### Scenario: A missing reading
- **WHEN** a scalar source returns no reading for a tick
- **THEN** the processor publishes no value for that tick and does not adapt its forward model on it

### Requirement: No source persists sense data, and records hash device identities
No source SHALL write a frame, audio sample or sensor reading to disk or to the bus. The run manifest SHALL carry each descriptor only when the registry is on. Records and events SHALL carry device identities only as a 16-hex SHA-256 prefix. The availability and selection events SHALL carry only `source_id`, `state`, `reason_label`, `by` and `epoch`, and the research-event allowlist SHALL list exactly those fields. The static zero-persistence test SHALL cover every file of this capability.

#### Scenario: A camera's serial number
- **WHEN** the device source binds a camera whose by-id name contains its serial number
- **THEN** no record, event or log line contains the by-id name, and the manifest carries its hash
