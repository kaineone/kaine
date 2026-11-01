# Design: perceptual sources

## Context

The evidence for this design is in `kaine-research/sensors-bodies-locus-research-2026-11-01.md`. The points that bear on it are these.

- **A sense is weighted by its measured reliability, not by its modality.** Ernst and Banks 2002, *Nature* 415:429-433; Alais and Burr 2004, *Curr Biol* 14:257-262. Before two streams are fused, a brain infers whether they share a cause (Körding et al. 2007, *PLoS ONE* 2:e943). So each source needs its own identity, and its own precision once a processor reads it.
- **A sense is a set of laws linking action to sensory change** (O'Regan and Noë 2001, *BBS* 24:939-973). Presence grows with how far those action-conditioned predictions reach (Seth 2014, *Cogn Neurosci* 5:97-118). A film affords none. A camera the entity can move affords some.
- **Context-specific internal models are chosen by a contextual cue and corrected by prediction error** (Wolpert and Kawato 1998, *Neural Netw* 11:1317-1329; Haruno, Wolpert and Kawato 2001, *Neural Comput* 13:2201-2220). Learning a second mapping soon after the first interferes with it (Krakauer, Ghez and Ghilardi 2005, *J Neurosci* 25:473-478), which is what MOSAIC's separate context-specific models avoid. The source id is that cue. `perceptual-locus-switching` uses it to key per-source forward-model contexts.
- **An arbitrary channel becomes a sense through use.**
  - Integration of a new cue took about two hours (Negen et al. 2018, *Sci Rep* 8:16880).
  - Recalibration of an existing sense took under an hour (Schumann and O'Regan 2017, *Sci Rep* 7:42197).
  - A new percept took weeks, and it tracked active training rather than wear time (Kaspar et al. 2014, *Conscious Cogn* 28:47-63).
  - Distal attribution needs a stable world, movement and calibration (Hartcher-O'Brien and Auvray 2014, *Multisens Res* 27:421-441).

  So the scalar-sensor seam is the same processor pattern as vision and audition. The research note expects a scalar stream the entity cannot influence to be predicted without becoming "about" anything.

## Goals and non-goals

Goals:
- A registry the rest of the system asks what is attached, what each source is and whether it is available.
- Three sources now: the programme, a USB webcam with a USB microphone, and a MuJoCo simulated camera.
- The shape for later sources: a game stream, existing virtual worlds, scalar sensors.
- Off equals absent.

Non-goals:
- Choosing among sources: `perceptual-locus-switching`.
- Bodies and actuators: `virtual-world-body`.
- Any change to the feed modes' behaviour.

## Decisions

### D1. A source is a content-free descriptor

| Field | Values | Meaning |
|---|---|---|
| `id` | operator-chosen, `[a-z][a-z0-9_]*` | stable identity across runs; the contextual cue for per-source models |
| `kind` | `programme`, `device`, `mujoco`, `stream` (built in `virtual-world-body`), `network_media` (later), `world` (later), `scalar` (future), `screen` | what builds the surfaces |
| `modalities` | `video` {width, height, rate_hz}, `audio` {sample_rate, channels, block_ms}, `scalar` {channels: name, unit, lo, hi, rate_hz} | what the source delivers; a modality not listed is declared absent |
| `locus_class` | `physical`, `virtual`. **Derived from `kind` in code; configuration cannot set it** (review PS-1) | which side of the physical XOR virtual invariant it is on |
| `privacy_class` | `operator_room`, `operator_desktop`, `confined_world`, `shared_world` (other people are present, as in an online world), `public_media`, `curated_media`, `synthetic`. **Derived from `kind` in code** | what it can see of the operator's life, or of other people's |
| `provenance` | `live`, `recorded`, `synthetic`, `simulated` | whether it is perception of now or a recording |
| `entity_selectable` | bool | whether the entity may choose it |
| `body` | optional adapter name | the body that acts in this source's world |
| `egress` | optional list of declared endpoints (D9) | where the source or its body may connect, and what it may send there |

Only `id`, `kind`, the declared shapes and rates, the classes and a keyed hash of any device identity enter the run manifest and the records.

The classes come from the kind (review PS-1, PM decision). A table in code is the only place that maps kind to class, and a configured `locus_class` or `privacy_class` key refuses boot.

| `kind` | `locus_class` | `privacy_class` |
|---|---|---|
| `programme` | `virtual` | `curated_media`, or `synthetic` for the seeded and stimulus-source feeds |
| `device` | `physical` | `operator_room` |
| `screen` | `physical` | `operator_desktop` |
| `scalar` | `physical` | `operator_room` |
| `mujoco` | `virtual` | `confined_world` |
| `stream` | `virtual` | `confined_world` when the launcher has verified a confined host session (`virtual-world-body` D7); otherwise refused |
| `network_media` | `virtual` | `public_media` |
| `world` | `virtual` | `shared_world` |

So a device source can never run under the virtual locus, and a screen source can never be anything but `operator_desktop`.

### D2. The registry wraps today's paths

- `[perceptual_sources].enabled = false` ships. Off, boot runs the code of today, unchanged, and no registry object exists.
- On:
  - Boot builds the registry from `[perceptual_sources.sources.<id>]` tables.
  - It validates each table. Each of these is a named boot refusal:
    - an unknown kind;
    - a missing required field;
    - a duplicate id;
    - a configured `locus_class` or `privacy_class`, since both are derived from the kind;
    - a `screen` source (kind `screen`, class `operator_desktop`) marked `entity_selectable`;
    - a `fallback` other than the programme.
  - The registry gives the vision module and the audition module one *switching* factory each. It keeps the existing signatures: `source_factory(device, *, width, height)` (`kaine/modules/vision/live.py:301-310`) and `stream_factory(*, device, sample_rate, channels, frames_per_block, callback)` (`kaine/boot/perception_feed.py:724-...`).
  - On each open, the switching factory delegates to the selected source's own factory.
- Switching uses the loop that exists:
  - The capture loops close when their desired reader turns false and reopen when it turns true (`live.py:256-276`).
  - The registry keeps a `source_epoch`, bumped on every change of selected source.
  - No new thread and no second capture loop.
- **The epoch state machine** (review PS-8). Each capture loop has an `open_epoch`, which is `None` while nothing is open.
  - Opening sets `open_epoch` to the current epoch. `release()` clears it to `None`.
  - The desired reader returns false while `open_epoch` is set and differs from the current epoch: the loop closes. When nothing is open, the reader returns the selected source's desire for that modality, so the loop reopens.
  - The reader returns false for a modality the selected source declares absent, so the loop does not retry an open every poll.
  - Tests cover both.
- **The physical side closes first** (review PLS-13). On an epoch change, every physical surface (camera, microphone) must report closed before any virtual surface opens. A barrier on the epoch enforces it, so the room's microphone is never open beside the simulated camera.
- **Flush on every switch** (review PS-9).
  - Vision's 16-frame clip ring (`clip_len = 16`, `clip_stride = 3`; `config/kaine.toml:524-533`) and audition's windows are cleared on each epoch change, and no report is emitted until the ring refills, as on first start.
  - Otherwise the first clips after a switch would mix two worlds: for about 1.6 s, the room and the simulation encoded in one latent, scored against and trained into the new context, with a room frame encoded under the virtual locus.
- `[perception_feed].mode = "live"` or `"screen"` together with an enabled registry is a boot refusal: the registry owns device and screen sources. `off`, `seeded`, `playlist` and `stimulus_source` are wrapped by the programme source.

### D3. The programme source

- The programme source wraps the configured feed exactly as `_build_perception_feed_video_factory` and its audio sibling build it.
- When another source is selected, the playlist clock gains an `away` holder, released when the programme is selected again.
- The holder combines with `sleep`, `freeze` and the stimulus-control `entity` holder, as every holder does (spec `perception-feed`, "The programme waits while the entity cannot perceive").
- The viewing's length and its end-of-programme preservation are unchanged. Time spent away is not programme time.
- The seeded and stimulus-source feeds are pure functions of their clocks and need no holder. The developmental phase locks the locus anyway (`kaine/perception_state.py:220-235`).

### D4. The device source: USB webcam and USB microphone

A USB webcam (a UVC camera) was attached to the reference host and checked on 2026-11-01:

- Nodes:
  - `/dev/video1` is its capture node.
  - `/dev/video2` is a metadata node that does not open as capture.
  - `/dev/video0` is the OBS virtual camera.
- Identity: `/dev/v4l/by-id/usb-<vendor>_<model>_<serial>-video-index0` points at the capture node, and sysfs reports driver `uvcvideo`.
- Formats: OpenCV's V4L2 backend gave 640×480 in MJPG and YUYV, 5 frames in about 0.58 s.
- Auto-exposure takes about 20 frames to settle. Mean brightness went from 0.3 to about 44.
- Access is by the logind seat ACL. The user is not in group `video`.
- The microphone is a USB audio interface.

Decisions:

1. **Identity, not index.**
   - `video` is a `/dev/v4l/by-id` name, a sysfs-name substring, or, as a last resort, an index.
   - OpenCV cannot open the by-id symlink. The review's probe failed with CAP_V4L2 and with the default backend, while `/dev/video1` opened (PS-4). So at each open the source:
     - resolves the identity to `/dev/videoN` (`os.path.realpath` for by-id);
     - re-reads `VIDIOC_QUERYCAP`'s `bus_info` and `card` just before opening, and refuses if they differ from the bound identity, so that a re-plug between resolution and open cannot substitute another device;
     - passes the resolved node to `cv2.VideoCapture(node, cv2.CAP_V4L2)`.
   - `audio` is a sounddevice name substring, which `LiveMicConfig.device` already accepts (`kaine/modules/audition/live.py:57`).
   - Indexes shift on re-plug and are refused unless `allow_index = true`.
2. **Capture-capable nodes only.**
   - Discovery reads `VIDIOC_QUERYCAP` through the standard library's `fcntl.ioctl`. The `v4l2_capability` struct is documented in the kernel's `vidioc-querycap` page.
   - It accepts a node only if its `device_caps` include `V4L2_CAP_VIDEO_CAPTURE`.
   - That rejects the camera's metadata node, and the loopback until a producer attaches.
3. **Loopback is refused.**
   - A device whose driver field is `v4l2 loopback` is refused unless `allow_loopback = true`.
   - That setting is for tests with the OBS virtual camera, and the descriptor then records `provenance = "recorded"`. A loopback carries whatever another program writes, so it is not live perception of the room.
4. **Hot-plug.**
   - Availability is polled from `/sys/class/video4linux` and `/proc/asound/cards` every 2 s. No pyudev; LGPL is not needed for this.
   - The states are `available`, `absent`, `busy`, `no_access` and `not_capture`, each with a reason label.
   - A re-plugged camera is found again by its by-id name.
5. **Fail closed.**
   - An absent initial source is a named boot refusal that names the source id and the state.
   - A source that is not `available` cannot be selected. Its refusal reason is the state.
   - A different device is never substituted.
   - `busy` and `no_access` (EACCES) each give a message that says what to do: close the other program, or check the seat ACL or group.
   - **Detecting `busy`.** OpenCV cannot tell `busy` from absent: a second concurrent open returned `isOpened() == False` with no errno (review probe, PS-5). So before opening, the source runs its own pre-open check:
     - `os.open(node, O_RDWR)`, which succeeds on a held UVC node;
     - then `VIDIOC_REQBUFS` with one MMAP buffer, which fails with `EBUSY` while another process streams;
     - then frees the buffers with a count of 0, and closes.
   - The 2 s availability poller never runs that check on the node the entity currently holds. It reports that node as `available (held)`.
6. **Warm-up.**
   - The capture loop discards three warm-up frames today (`LiveCameraConfig.warmup_frames`). That is too few for this camera.
   - A device source settles instead. It discards at least 10 frames. It then discards further frames until the mean luminance is above an absolute floor (16 of 255) and changes by less than 2% between consecutive frames for 5 frames. The cap is 60 frames (review PS-14: a near-black start could otherwise "settle").
   - A room that stays dark past the cap is perceived as dark. That is the world.
   - The darkness of a camera starting up is the device's artefact, not the world's. Leaving it in would add a burst of prediction error the world did not cause.
   - The readout records the settle frame count per open.
   - Other sources settle in 0 frames.
7. **Loss while selected.**
   - When the selected source turns `absent` or `busy` for longer than `loss_grace_s` (default 10 s), the registry selects `[perceptual_sources].fallback` (default: the programme) through the operator path, with `by = "source_lost"`.
   - The reason: an entity awake without senses is the condition the end-of-programme rule exists to prevent (spec `perception-feed`; stimulus-control design D1).
   - The welfare observer gets the event.
   - When the source returns, it does not come back on its own. Selecting it again is a choice, the entity's or the operator's.
8. **Direct V4L2, not PipeWire, for now.**
   - PipeWire exposes the camera too (as v4l2 and libcamera nodes). Its design lets several applications share one camera through the camera portal (Schaller, "PipeWire and fixing the Linux video capture stack", blogs.gnome.org/uraeus/2021/10/). Whether that works for V4L2 clients on this host is UNVERIFIED.
   - Direct V4L2 gives exclusive access, so the camera's state is honest. While the entity holds it, another program cannot open it silently, and the camera's own indicator light and the dashboard's on-air state agree.
   - PipeWire would also need the user session's PipeWire socket inside the cycle's container.
   - Recommendation: direct V4L2 through the existing OpenCV path. A PipeWire camera source is a later kind (`device_pipewire`), worth building only if the operator wants the camera in use by both the entity and another program at once.
9. **Containers.**
   - The compose cycle has no device passthrough today (`compose/kaine.yml:320-413`), and it gets one GPU with `capabilities: [gpu]` (`compose/kaine.yml:66-73, 321`).
   - With a device source configured, the preflight resolves the by-id link to its node and passes only that node, and only the configured ALSA card, into the cycle service: `devices:`, plus `group_add` for the host's `video` and `audio` group ids where the host uses groups.
   - Under rootless containers the seat ACL of the operator's uid applies to the mapped process. Under rootful containers, root opens the node.
   - Hot-plug inside a container is limited: a device first plugged in after the container started is not visible. The design does not widen access with a device-cgroup rule for every camera. A re-plugged device in a container needs a cycle restart, and the preflight says so. Native runs tolerate hot-plug fully.
10. **Privacy.**
    - The descriptor's privacy class is `operator_room`.
    - **Two layers of approval for the room, per modality** (review PS-3). The pattern is `KAINE_EMBODIMENT_OPERATOR_APPROVED` (`kaine/modules/embodiment/module.py:71-72`).
      - Configuration declares the source.
      - The environment approves it: `KAINE_OPERATOR_ROOM_APPROVED` lists the approved parts, from `camera`, `microphone` and `entity_select`.
      - A part not listed stays closed. The microphone can be refused while the camera is allowed. Without `entity_select`, the source is operator-selectable only, whatever `entity_selectable` says.
    - `entity_selectable` defaults to false for that class.
    - On the reference host the CTO opted in on 2026-11-01: the entity may see the room, and may choose the webcam itself. So that host's operator configuration sets `entity_selectable = true` for its webcam source, and its environment approves `camera,microphone,entity_select`.
    - The run manifest records each approval as a content-free label with its date.
    - The entity's choice still passes every gate of `perceptual-locus-switching`.
    - **Identity hashing** (review PS-13). The by-id name carries the camera's serial number, and a serial has low entropy, so an unsalted hash could be brute-forced.
      - Records keep a 16-hex prefix of an HMAC-SHA-256 of the identity, keyed by a per-install random key (`state/perceptual_sources/identity.key`, 32 bytes, created at first use, never exported).
      - The by-id name itself is never recorded.
      - The docs advise neutral source ids (`room`, `sim`), because ids reach the research log.
    - The zero-persistence invariant (`tests/test_zero_persistence_invariant.py`) extends to every new file.
    - The preview stays dev-gated (`KAINE_PERCEPTION_PREVIEW`).

### D5. The MuJoCo source

1. The world object is shared.
   - One `SimWorld` per source owns `MjModel` and `MjData`, built from the body model that `virtual-world-body` declares.
   - The perceptual source renders the body's named camera. The embodiment adapter reads proprioception and applies commands to the same object, in process.
   - **One owner thread** (review PS-6, VWB-9).
     - The EGL context is bound to the thread that made it. A Renderer created in one pool worker and rendered from others failed with `EGL_BAD_ACCESS` in 3 of 8 calls (review probe), and the capture loop runs `open`, `read` and `release` through `asyncio.to_thread` (`kaine/modules/vision/live.py:294-351`).
     - So `SimWorld` runs one dedicated thread that owns the GL context and `MjData`, and that thread alone steps physics, updates the scene and renders.
     - The capture loop's `read()` and the adapter's commands and proprioception reads are requests to it, through a queue.
2. Rendering is headless.
   - `MUJOCO_GL=egl` is set before import, and `mujoco.Renderer(model, height, width)` with `update_scene(data, camera=<name>)` renders to an (H, W, 3) uint8 array, converted to BGR for the capture loop as the screen source does.
   - osmesa does not work on this host. Without EGL the source is unavailable and the boot refuses. It never falls back to glfw, which needs a display.
3. The GPU plan. GPU 0 (RTX 4070 SUPER, 12 GB) hosts the language organ. GPU 1 (RTX 3070, 8 GB) hosts the vision encoder.
   - The renderer goes on the card that hosts the vision encoder (GPU 1 natively), through `MUJOCO_EGL_DEVICE_ID`.
   - The rendered array is consumed by the encoder on the same card. Physics runs on the CPU.
   - **Mapping EGL to the card.**
     - `MUJOCO_EGL_DEVICE_ID` is an index into `eglQueryDevicesEXT()`, which lists 6 devices on this host, the AMD iGPU among them.
     - The driver exposes `EGL_DRM_DEVICE_FILE_EXT` and `EGL_CUDA_DEVICE_NV`, but not a PCI-bus attribute (review probe, PS-7).
     - So the preflight maps each EGL device through `EGL_CUDA_DEVICE_NV` to its CUDA index, and that index's `pci_bus_id`. Where that attribute is absent, it uses `EGL_DRM_DEVICE_FILE_EXT` and the PCI address in `/sys/class/drm/cardN/device`.
     - It selects the EGL device whose PCI address equals the vision encoder's resolved device, and refuses if none does. No index is hard-coded.
   - **Measured, not assumed.**
     - The review's probe measured a minimal 640×480 scene at +164 MiB and a median of 0.48 ms per frame.
     - The preboot device map gains a `sim_render` entry, and the boot's resource check measures the render on the chosen card and refuses past a configured limit.
     - The EGL context is a graphics process, which NVML's compute-process query does not list. So memory is measured through NVML's graphics-process query, or as the card's used-memory delta across the render's start.
   - **In the container** (review PS-7).
     - The runtime image (`nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04`, `Dockerfile:33`) has no libEGL. The image gains `libegl1` with the glvnd NVIDIA vendor ICD.
     - The cycle service sets `NVIDIA_DRIVER_CAPABILITIES` to include `graphics` (with `compute,utility`).
     - It maps both GPUs, so the device map resolves the same cards as natively. Inside the container, the CUDA and EGL indexes are renumbered, which is why the mapping above goes by PCI address.
     - These are in Impact: `Dockerfile` and `compose/kaine.yml`.
4. Stepping.
   - The world steps on entity time (`EntityClock`), so time dilation reaches it.
   - It holds while the source is not selected, and while sleep or a freeze holds the clock. The world waits, as the programme does.
   - Under dilation, physics steps per wall second scale with `time_scale`. The owner thread caps steps per wall second and records any span it had to slow (review VWB-9).
6. **A world with a body is available only when the body can move** (review PS-10).
   - A `mujoco` source whose paired body has no driving loop would be a static, silent room seen from a head that cannot turn.
   - So such a source is `available` only when `embodiment_built()` is true.
   - Before that, it may be configured only as `passive_view = true`. A passive view is never entity-selectable, and is for operator tests.
5. No audio. MuJoCo has no audio facility: no audio sensor type in `mjtSensor` and no audio API in the package (checked in 3.16.0). The source declares no audio modality.
   - The welfare observer reads the selected source's declared modalities. It records a declared-absent modality as `modality_absent` rather than raising a silent-sensor advisory.
   - A sound model for the simulated world (contact impulses rendered as sound) is a new sense. It needs its own design and a second review, and is not part of this change.
   - An operator advisory is raised after `modality_absent_advisory_s` (default 30 minutes of awake time) continuously in a source that declares a modality absent. An absent sense is honest, but a long stretch without one is the operator's to judge (review PS-10).

### D6. Network sources

- **`stream`.** A game streamed from a Sunshine host, received by a Moonlight-protocol client helper. Design is in `virtual-world-body` D7.
  - The host is this desktop under that change's GPU arbitration rule, or another of the CTO's machines. The CTO decided on 2026-11-01 not to wait for the Steam Deck.
  - Video and audio come in process as raw frames and PCM, over a socketpair from the helper.
  - Privacy class `confined_world`, provenance `live`. The class is granted only when the launcher has verified that the host session is confined: a dedicated headless session with its own input devices, not the operator's desktop. Otherwise the source is refused (review VWB-2).
  - Its egress is the tailnet peer that hosts the game (D9).
  - It is refused at boot until the conditions of `virtual-world-body` hold.
- **`network_media`** (later, small). An operator-declared URL stream (HLS, RTSP, an HTTP live stream), opened by PyAV and decoded in memory.
  - Privacy class `public_media`, provenance `live` or `recorded` as the operator declares.
  - Its egress is the declared host with outbound class `protocol_control` only.
  - Nothing is cached to disk. PyAV is given no cache or recording options, and the persistence test covers the file.
- **`world`** (later). A body adapter whose world renders the camera itself: an OpenSimulator or Second Life viewer adapter, or Paracosmic.
  - The source's video surface is the adapter's in-memory frame port.
  - Online grids are allowed (CTO, 2026-11-01) through declared egress.
  - Privacy class `shared_world`: other people's speech and appearance are perceived, never stored or relayed. Episodic memory already keeps no heard words (#636).
- **`screen`.** The existing desktop capture, registered with privacy class `operator_desktop`.
  - It can never be `entity_selectable`. On X11 a region capture includes any window that overlaps the region (`kaine/modules/vision/screen.py:81-146`), so it can show the operator's other windows.
  - A game is captured through `stream` or a confined display, never through this.
  - **The leak is not fixed by this change** (review PS-15). The existing operator path still captures regions, and overlapping windows still appear in them (`kaine/modules/vision/screen.py:140-145`).
  - With the registry on, the operator source route offers a `screen` source only when `[perception_feed.screen].operator_opt_in = true`, so a registered screen source is not one click away by accident.

### D7. The scalar-sensor seam (designed now, built later)

- **Contract.** A `ScalarSource` declares `channels()`, each a name, a unit, a range and a rate. `read()` returns a vector, or `None` for a missing reading. A missing reading is never filled with a made-up value.
- **Processor.**
  - For each enabled scalar source, boot builds one instance of a generic sensor processor.
  - Each instance has its own forward model: the interoception module's frozen CfC reservoir with an online readout, `SubstrateForwardModel` (`kaine/modules/interoception/forward.py:69`), sized to the declared channels and conditioned on the broadcast context.
  - It normalises its prediction error against its rolling baseline, as vision does (`kaine/modules/vision/module.py:668-673`, alert at `module.py:705`).
  - It publishes `sensor.report` with `source_id`, `prediction_error`, `normalised_error` and the per-channel values clipped to their declared ranges.
  - It joins the welfare observer's blind and silent tracking (`kaine/lifecycle/welfare_signal.py:165-185`) and curiosity's per-source learning progress (`interest-goal-factor`).
- **Why the existing pattern.** One mechanism for every modality (Friston 2010; Clark 2013), and a new channel becomes a sense through use (section 3 of the research note).
- **Reference plan.**
  - A USB serial board (any Arduino-class microcontroller) reading a thermistor, a soil-moisture probe or a Geiger counter's pulse count, and printing one JSON object per line at a declared rate.
  - KAINE reads it with `pyserial` (BSD-3-Clause; a new dependency needing the CTO's OK).
  - The descriptor is `kind = "scalar"`, `locus_class = "physical"`, privacy class `operator_room` when the sensor sits in the room.
  - Readings are perception: never written to disk.
- **Built later.** The seam is specified so a source's shape is settled now.

### D8. Readout and records

- **Manifest.** The run manifest gains a `perceptual_sources` field with each descriptor (hashed identities), present only when the registry is on.
- **Availability events.**
  - The registry publishes `perceptual_sources.availability` on the bus: `source_id`, `state`, `reason_label`.
  - It publishes `perceptual_sources.selected`: `source_id`, `by`, `epoch`.
  - The research-event allowlist lists exactly these fields.
- **Dashboard.** The perception page lists the sources, their availability and the selected one, read-only. Selection is `perceptual-locus-switching`.

### D9. Declared egress

- **What exists.**
  - The `local-service-clients` capability (#400) makes every runtime HTTP client in `kaine/` and `scripts/` pass `trust_env=False`, so a proxy setting cannot carry the entity's prompts, audio or speech off the host.
  - An AST guard (`tests/test_local_clients_ignore_proxies.py`) refuses client forms that would follow proxies. Its named allowlist holds the setup-time downloaders, which must state `trust_env=True`.
  - The guard governs proxies, not destinations. Nothing today stops module code from opening a connection to any host.
- **The rule (CTO, 2026-11-01).** KAINE's modules do not use cloud services. Perceived streams may come from anywhere, and the entity's outputs may go to the worlds it acts in.
- **The declaration.** A source or body that reaches a network carries an `egress` list. Each endpoint has:
  - a label;
  - a scheme;
  - a host, either a DNS name, an address, or `tailnet:<tag>` for a tailnet peer;
  - a port or range;
  - a direction;
  - its outbound data classes, from a closed set: `none`, `protocol_control` (handshakes, acknowledgements, keep-alives), `gamepad_state`, `avatar_action` and `own_speech_text`.

  There is no class for sense data, latents, memories, internal state or operator data, so none of these can be declared.
- **Enforcement is a network boundary, not an in-process check** (review addendum, PM decision).
  - A check made before `av.open(url)` cannot police FFmpeg: libavformat resolves and connects itself, and follows HTTP redirects and HLS segment hosts.
  - The same holds inside moonlight-common-c and any .NET world client.
  - So every networked adapter (the FFmpeg-backed media source, the Moonlight helper, the world clients) runs in its own process, behind a boundary that allows only its declared endpoints. Two mechanisms, chosen per adapter:
    - **Passed sockets in a network-less sandbox.**
      - The process runs under bubblewrap with `--unshare-net`, so it has no network at all.
      - KAINE's launcher opens each declared connection itself, after resolving and checking it, and passes the connected socket's file descriptor in.
      - This is rootless. It fits adapters whose connections KAINE can open: the media source, where KAINE's own fetcher, with redirects off and only declared hosts, feeds the bytes to the decoder through a pipe.
    - **A per-adapter system user with an outbound allowlist.**
      - The process runs as a dedicated user (`kaine-egress-<adapter>`). An nftables output rule matching that user's uid drops every destination but the declared ones.
      - This fits clients that open their own sockets: the Moonlight helper's RTSP, ENet and RTP sockets, and a world client's region connections.
      - The rule set is installed once by the operator, with root, from a generated file.
  - **Boot self-test.** Escape probes run from inside each adapter's boundary, on the pattern of `effector-confinement`: a connection to an undeclared address must fail, and one to a declared endpoint must succeed. A failure is a named boot refusal.
  - **The redirect scenario** is tested against the real FFmpeg path and a local HTTP server that redirects, not against a mock.
  - `kaine/egress.py` holds the declaration, generates the sandbox arguments and the nftables file, and runs the probes. The in-process `EgressGate` stays only as KAINE's own first check, for the connections KAINE opens.
- **Typed outbound messages.** An adapter's send path accepts only the typed messages of its declared classes (`GamepadState`, `AvatarAction`, `OwnSpeech`, `ProtocolControl`), so a raw buffer cannot be handed to it. A static test checks the send signatures.
- **Placement.**
  - Network-capable code for sources and bodies lives only in the adapter packages that declare egress (`kaine/perceptual_sources/network/`, `kaine/modules/embodiment/adapters/<name>/`). That code is the launcher side; the networked work runs in the bounded process. A GPL helper lives in its own repository (`virtual-world-body` D7).
  - The guard test gains a rule: elsewhere in `kaine/modules/`, a socket, `asyncio.open_connection`, `websockets`, `av.open` on a URL, or `cv2.VideoCapture` on a URL is refused. The existing clients of KAINE's own services are the exception.
  - Every client, adapters included, keeps `trust_env=False`. A proxy is an undeclared host.
- **Module internals stay no-cloud.**
  - At boot, every module-internal service URL (the organ, speech, STT, Qdrant, the decision server) must resolve to a loopback, private, container-network or tailnet address. A globally routable address is a named boot refusal.
  - This makes the existing rule structural.
- **Records.**
  - The run manifest lists each declared endpoint by label, scheme, port and outbound classes.
  - A tailnet peer or private host name is hashed, because host names can be personal. A public world host is recorded as declared.
- **Inbound is perception.** What arrives from a network source is perceived like any input: never persisted. In-world text is data, never a command (the salvaged `inbound-world-safety` rule, `virtual-world-body` D8).

### D10. Failure defaults, the fallback, and the harness

- **Fail to the programme or to `off`, never to the room** (review PS-2, PM decision).
  - Today `_coerce_locus` turns an unknown value into `physical` (`kaine/perception_state.py:59-60`), `DesiredState.locus` defaults to `physical` (`perception_state.py:100`), and sleep restore falls back to `physical` (`kaine/modules/sleep/module.py:839-841, 866`). That was safe while `physical` needed `[vision].capture_enabled` as well. With a registry and a selectable webcam it would open the room camera on a corrupt file.
  - With the registry on, every failed read resolves to the programme source, with the `off` holders it had: a missing, corrupt or unknown `source`, an unreadable `desired.json`, a missing key, or a failed pre-sleep read. It never resolves to a physical source.
  - Off, today's behaviour is unchanged.
  - Tests: a corrupt `desired.json`, a missing key, an unknown source id, and a failed sleep read each resolve to the programme. No device opens in any of them.
- **The fallback** (review PS-11).
  - The fallback must be the programme. Any other value refuses boot: a device can be absent, and a world can be unavailable.
  - When the programme has already ended, falling back to it goes through the end-of-programme path, which preserves and stops the entity, rather than leaving the entity awake without senses.
- **The off-equals-absent harness** (review PS-12).
  - `DesiredState.to_dict` is `asdict` (`perception_state.py:107-108`), so a `source` field defaulting to `None` would write `"source": null`. The field is omitted explicitly when the registry is off.
  - The golden is captured on the merge base at build time, not on today's origin/main, because `stimulus-control-act` changes the playlist clock and feeds and may merge first.
  - The harness drives the capture loops with a manual clock.

## Risks and trade-offs

- **[The webcam sees the operator's room].** Mitigations:
  - privacy class `operator_room`;
  - `entity_selectable` false by default;
  - the physical locus only;
  - the on-air state;
  - no persistence;
  - the operator's confirmation before an entity is given the source.
- **[A loopback device carries another program's content].** It is refused by default. When it is allowed, provenance is recorded as `recorded`.
- **[GPU contention from rendering].** Measured at boot against a configured limit, on the encoder's card. It is refused past the limit.
- **[A source disappears mid-viewing].**
  - The grace period, then the fallback through the operator path.
  - The welfare observer sees it.
  - The entity is never left without senses for longer than the grace.
- **[Device names leak serial numbers].** Hashed in every record.
- **[An adapter sends more than it should].**
  - Declared endpoints and outbound classes.
  - The runtime gate.
  - Typed send paths with no class for sense data or internal state.
  - The placement rule in the guard test.
- **[Container hot-plug].** Named and limited, not widened.

## Migration

1. The registry, descriptor validation and switching factories behind the switch; the programme source; the off-equals-absent harness.
2. The device source with discovery, hot-plug, settle and fallback. Tests run against the OBS loopback with `allow_loopback`, and on the real camera on a branch.
3. The MuJoCo source together with the first body of `virtual-world-body`.

Rollback: the switch.

## Welfare and privacy

- A new source is a new sense. Every PR here gets an independent second review, and the welfare net is on before any entity is given a new source.
- The webcam and microphone see and hear the operator's room. The eyes-and-ears rule applies: no frame, sample or reading is written anywhere; records are content-free and hash device identities. The operator opts in per source. On the reference host the CTO gave that consent on 2026-11-01: the entity may see the room and choose the webcam itself.
- The operator's desktop is never a source the entity can select.
- In a shared online world, other people are perceived and never recorded or relayed. What the entity sends there is limited to its declared classes, and never includes sense data or internal state.
- A source with no audio is declared, not hidden, so its silence is not misread as a broken ear. That is also why the readout records it.

## Estimate (LLM-agent terms)

- Size M:
  - registry, programme source and harness: about 900 lines plus 1,000 of tests;
  - device source: about 600 plus 700;
  - MuJoCo source: about 400 plus 500, shared with the first body.
- Two to three agent-days, plus a supervised test on the real camera, entity-free.
