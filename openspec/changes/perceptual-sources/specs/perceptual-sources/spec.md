## ADDED Requirements

### Requirement: Sources are declared as content-free descriptors
With `[perceptual_sources].enabled = true`, boot SHALL build a registry from the `[perceptual_sources.sources.<id>]` tables. Each source SHALL declare an `id`, a `kind`, its modalities with shape and rate, a `provenance`, `entity_selectable`, and an optional paired `body`. A modality a source does not list SHALL be treated as declared absent.

#### Scenario: A missing modality is declared absent
- **WHEN** a `mujoco` source lists only a `video` modality
- **THEN** its audio modality is declared absent, and the descriptor in the run manifest says so

### Requirement: The locus and privacy classes come from the kind
A source's `locus_class` and `privacy_class` SHALL be derived from its `kind` by one table in code: `device` and `scalar` are `physical` and `operator_room`; `screen` is `physical` and `operator_desktop`; `programme`, `mujoco`, `stream`, `network_media` and `world` are `virtual`. A configured `locus_class` or `privacy_class` SHALL refuse boot.

#### Scenario: A device declared virtual
- **WHEN** a `device` source is configured with `locus_class = "virtual"`
- **THEN** boot refuses, naming the source and the rule that classes come from the kind

### Requirement: Invalid source configurations refuse boot
Boot SHALL refuse with a named configuration error on an unknown kind, a missing required field, a duplicate id, an absent initial source, a fallback other than the programme, `[perception_feed].mode` set to `live` or `screen` while the registry is on, or a `screen` source marked `entity_selectable`.

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
A `device` source SHALL identify its camera by a `/dev/v4l/by-id` name or a sysfs-name substring, and its microphone by a sounddevice name substring. An index SHALL be accepted only with `allow_index = true`. At each open it SHALL resolve the identity to `/dev/videoN`, re-read the node's `bus_info` and `card`, refuse if they differ from the bound identity, and open the resolved node.

#### Scenario: Re-plugged camera
- **WHEN** the configured camera is unplugged and plugged into another port
- **THEN** the source finds it again by its by-id name, resolves its new node, and opens that node

#### Scenario: A different device on the old node
- **WHEN** between resolution and open another device takes the resolved node
- **THEN** the open is refused, and no other device is opened

### Requirement: A device source accepts only real capture nodes
Discovery SHALL accept only a node whose `VIDIOC_QUERYCAP` device capabilities include video capture. It SHALL refuse a node whose driver is `v4l2 loopback` unless `allow_loopback = true`, in which case the descriptor's provenance SHALL be `recorded`.

#### Scenario: The metadata node is not a camera
- **WHEN** a UVC camera exposes a capture node and a metadata node
- **THEN** discovery binds the capture node and reports the metadata node as `not_capture`

#### Scenario: The OBS virtual camera
- **WHEN** the only video node is a v4l2 loopback and `allow_loopback` is false
- **THEN** the device source is not available, and the reason says it is a loopback

### Requirement: A device source fails closed
Availability SHALL be polled at least every 2 s and SHALL be one of `available`, `absent`, `busy`, `no_access` or `not_capture`. `busy` SHALL be detected by a pre-open check that requests capture buffers and reads `EBUSY`. The poller SHALL NOT run that check on the node the entity holds. A source that is not `available` SHALL NOT be opened, no other device SHALL be substituted, and each refusal SHALL state what the operator can do.

#### Scenario: The camera is held by another program
- **WHEN** another program is streaming from the camera
- **THEN** the pre-open check reads `EBUSY`, the source is `busy`, nothing is opened, and the message says another program holds the camera

### Requirement: A device source discards the camera's warm-up
On each open a device source SHALL discard at least 10 frames, then discard frames until the mean luminance exceeds an absolute floor and changes by less than 2% between consecutive frames for 5 frames, or until 60 frames have been discarded, and SHALL record the number discarded. No discarded frame SHALL reach the vision module.

#### Scenario: Auto-exposure settling
- **WHEN** the camera's brightness rises over its first 20 frames
- **THEN** the vision module receives its first frame only after the brightness has settled, and the record states how many frames were discarded

### Requirement: Losing the selected source returns the entity to the programme
When the selected source stays `absent` or `busy` for longer than `[perceptual_sources].loss_grace_s` (default 10 s), the registry SHALL select the programme through the operator path, recorded with `by = "source_lost"`, and SHALL publish the change. If the programme has ended, the end-of-programme path SHALL apply. A returning source SHALL NOT be reselected automatically.

#### Scenario: The webcam is unplugged
- **WHEN** the selected webcam is unplugged and does not return within the grace period
- **THEN** the programme is selected with `by = "source_lost"`, and the welfare observer receives the event

### Requirement: The MuJoCo source renders headless on the planned card
A `mujoco` source SHALL render with `MUJOCO_GL=egl` on the EGL device whose PCI address, found through the CUDA or DRM device attribute, equals the vision encoder's device. It SHALL refuse at boot when EGL is unavailable or no device matches, SHALL NOT fall back to a display-bound backend, and SHALL refuse past the configured limit on the render's measured memory and time per frame.

#### Scenario: No EGL
- **WHEN** EGL cannot be initialised
- **THEN** boot refuses, naming the `mujoco` source and the missing backend

### Requirement: One thread owns the simulated world
The simulated world's physics stepping, scene update and rendering SHALL run on one owner thread, which holds the GL context, and every other reader or writer SHALL reach the world through requests to that thread.

#### Scenario: Reads from the capture loop
- **WHEN** the capture loop requests frames from several worker threads
- **THEN** every render runs on the owner thread, and no `EGL_BAD_ACCESS` occurs

### Requirement: A world whose body cannot move is not offered to the entity
A `mujoco` source with a paired body SHALL be `available` only when `embodiment_built()` is true. Before that it MAY be configured as a passive view, which SHALL never be entity-selectable.

#### Scenario: Before the driving loop exists
- **WHEN** the simulated body exists and the driving loop does not
- **THEN** the source is not available to the entity

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
A source of kind `stream`, `network_media`, `world` or `scalar` SHALL be refused at boot with a named reason until the change that builds it has merged and its own start conditions hold.

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
No source SHALL write a frame, audio sample or sensor reading to disk or to the bus. The run manifest SHALL carry each descriptor only when the registry is on. Records and events SHALL carry device identities only as a 16-hex prefix of an HMAC-SHA-256 keyed by a per-install key. Availability and selection events SHALL carry only `source_id`, `state`, `reason_label`, `by` and `epoch`, and the research allowlist SHALL list exactly those.

#### Scenario: A camera's serial number
- **WHEN** the device source binds a camera whose by-id name contains its serial number
- **THEN** no record, event or log line contains the by-id name, and the manifest carries its keyed hash

### Requirement: Room sources need a second, per-modality approval
A source of privacy class `operator_room` SHALL open a modality only when the environment approval `KAINE_OPERATOR_ROOM_APPROVED` lists it (`camera`, `microphone`), and SHALL be entity-selectable only when the source sets `entity_selectable = true` and the approval lists `entity_select`. Each approval SHALL be recorded in the run manifest as a label with its date.

#### Scenario: Camera approved, microphone not
- **WHEN** the approval lists `camera` and `entity_select` but not `microphone`
- **THEN** the room camera may open, the room microphone stays closed, and the source is entity-selectable

### Requirement: Networked sources and bodies declare their egress
A source or body adapter that opens a network connection SHALL declare each endpoint: a label, a scheme, a host or `tailnet:<tag>`, a port or range, a direction, and its outbound data classes from the closed set `none`, `protocol_control`, `gamepad_state`, `avatar_action` and `own_speech_text`. A networked adapter without a declaration SHALL refuse boot.

#### Scenario: An undeclared world client
- **WHEN** a world adapter that opens a connection is configured with no `egress` list
- **THEN** boot refuses, naming the adapter

### Requirement: Each networked adapter runs behind a network boundary
Each networked adapter SHALL run in its own process behind a boundary that allows only its declared endpoints: either a network-less sandbox that receives sockets KAINE opened after checking them, or a dedicated user with an outbound allowlist. Boot SHALL run escape probes from inside each boundary and SHALL refuse unless an undeclared address fails and a declared endpoint succeeds. Every client SHALL pass `trust_env=False`.

#### Scenario: A redirect to another host
- **WHEN** a media server, tested through the real FFmpeg path, redirects to an undeclared host
- **THEN** the connection does not leave the boundary, and the operator sees the advisory

### Requirement: Only declared data classes cross an egress
An adapter's send path SHALL accept only the typed messages of its declared outbound classes. No outbound class SHALL exist for sense data, latents, memories, internal state or operator data.

#### Scenario: A frame handed to a send path
- **WHEN** code passes a frame buffer to a world adapter's send path
- **THEN** a static check fails the build, because no declared message type carries it

### Requirement: Module internals stay off the public network
Network-capable code for sources and bodies SHALL live only in adapter packages that declare egress or in separate helper programs, and the guard test SHALL refuse sockets, websockets, or URL opens by PyAV or OpenCV elsewhere in `kaine/modules/`, except for the existing clients of KAINE's own services. At boot, every module-internal service URL SHALL resolve to a loopback, private, container-network or tailnet address. A globally routable address SHALL refuse boot.

#### Scenario: An organ URL on the internet
- **WHEN** the language organ's URL resolves to a globally routable address
- **THEN** boot refuses, naming the module and the URL's label

### Requirement: A failed state read resolves to the programme, never to the room
With the registry on, a missing, corrupt or unknown `source`, an unreadable desired-state file, a missing key, or a failed pre-sleep read SHALL resolve to the programme source, and SHALL never resolve to a physical source.

#### Scenario: A corrupt desired-state file
- **WHEN** `state/perceptual_locus/desired.json` cannot be parsed while the webcam is entity-selectable
- **THEN** the programme is selected, and no camera or microphone opens

### Requirement: Capture loops follow an explicit epoch state machine
Each capture loop SHALL hold the epoch of its open source, cleared on release. The desired reader SHALL return false while an open source's epoch differs from the current one, false for a modality the selected source declares absent, and the selected source's desire otherwise. On an epoch change every physical surface SHALL close before any virtual surface opens.

#### Scenario: From the webcam to the simulation
- **WHEN** the selected source changes from the webcam to the simulated world
- **THEN** the room camera and microphone report closed before the simulated camera opens, and the audio loop does not retry an open while the simulation is selected

### Requirement: A switch flushes the clip ring and the audio windows
On each epoch change vision's clip ring and audition's windows SHALL be cleared, and no report SHALL be emitted until they refill.

#### Scenario: No mixed clip
- **WHEN** the selected source changes
- **THEN** no clip contains frames of both sources

### Requirement: The operator route offers screen capture only by explicit opt-in
With the registry on, the operator source route SHALL offer a `screen` source only when `[perception_feed.screen].operator_opt_in = true`.

#### Scenario: No opt-in
- **WHEN** a `screen` source is registered without the opt-in
- **THEN** the operator route does not offer it
