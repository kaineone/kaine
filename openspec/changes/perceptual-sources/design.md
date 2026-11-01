# Design: perceptual sources

## Context

The evidence for this design is in `kaine-research/sensors-bodies-locus-research-2026-11-01.md`. The points that bear on it are these.

- **A sense is weighted by its measured reliability, not by its modality.** Ernst and Banks 2002, *Nature* 415:429-433; Alais and Burr 2004, *Curr Biol* 14:257-262. Before two streams are fused, a brain infers whether they share a cause (Körding et al. 2007, *PLoS ONE* 2:e943). So each source needs its own identity, and its own precision once a processor reads it.
- **A sense is a set of laws linking action to sensory change** (O'Regan and Noë 2001, *BBS* 24:939-973). Presence grows with how far those action-conditioned predictions reach (Seth 2014, *Cogn Neurosci* 5:97-118). A film affords none. A camera the entity can move affords some.
- **Context-specific internal models are chosen by a contextual cue and corrected by prediction error** (Wolpert and Kawato 1998, *Neural Netw* 11:1317-1329; Haruno, Wolpert and Kawato 2001, *Neural Comput* 13:2201-2220). Learning a second mapping in the same store interferes with the first. Kept apart, relearning shows savings (Krakauer, Ghez and Ghilardi 2005, *J Neurosci* 25:473-478). The source id is that cue. `perceptual-locus-switching` uses it to key per-source forward-model contexts.
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
| `locus_class` | `physical`, `virtual` | which side of the physical XOR virtual invariant it is on |
| `privacy_class` | `operator_room`, `operator_desktop`, `confined_world`, `shared_world` (other people are present, as in an online world), `public_media`, `curated_media`, `synthetic` | what it can see of the operator's life, or of other people's |
| `provenance` | `live`, `recorded`, `synthetic`, `simulated` | whether it is perception of now or a recording |
| `entity_selectable` | bool | whether the entity may choose it |
| `body` | optional adapter name | the body that acts in this source's world |
| `egress` | optional list of declared endpoints (D9) | where the source or its body may connect, and what it may send there |

Only `id`, `kind`, the declared shapes and rates, the classes and a hash of any device identity enter the run manifest and the records.

### D2. The registry wraps today's paths

- `[perceptual_sources].enabled = false` ships. Off, boot runs the code of today, unchanged, and no registry object exists.
- On:
  - Boot builds the registry from `[perceptual_sources.sources.<id>]` tables.
  - It validates each table: an unknown kind, a missing required field, a duplicate id, or a `screen` source marked `entity_selectable` is a named boot refusal.
  - The registry gives the vision module and the audition module one *switching* factory each. It keeps the existing signatures: `source_factory(device, *, width, height)` (`kaine/modules/vision/live.py:301-310`) and `stream_factory(*, device, sample_rate, channels, frames_per_block, callback)` (`kaine/boot/perception_feed.py:724-...`).
  - On each open, the switching factory delegates to the selected source's own factory.
- Switching uses the loop that exists:
  - The capture loops close when their desired reader turns false and reopen when it turns true (`live.py:256-276`).
  - The registry keeps a `source_epoch`, bumped on every change of selected source.
  - The desired reader returns false while the open source's epoch differs from the current one, so the loop closes the old source and opens the new one within one poll interval (250 ms).
  - No new thread and no second capture loop.
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
   - `busy` (EBUSY on open or stream-on: only one process can hold a V4L2 capture node) and `no_access` (EACCES) each give a message that says what to do: close the other program, or check the seat ACL or group.
6. **Warm-up.**
   - The capture loop discards three warm-up frames today (`LiveCameraConfig.warmup_frames`). That is too few for this camera.
   - A device source settles instead. It discards frames until the mean luminance changes by less than 2% between consecutive frames for 5 frames, capped at 60 frames.
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
   - The compose cycle has no device passthrough today (`compose/kaine.yml:320-413`).
   - With a device source configured, the preflight resolves the by-id link to its node and passes only that node, and only the configured ALSA card, into the cycle service: `devices:`, plus `group_add` for the host's `video` and `audio` group ids where the host uses groups.
   - Under rootless containers the seat ACL of the operator's uid applies to the mapped process. Under rootful containers, root opens the node.
   - Hot-plug inside a container is limited: a device first plugged in after the container started is not visible. The design does not widen access with a device-cgroup rule for every camera. A re-plugged device in a container needs a cycle restart, and the preflight says so. Native runs tolerate hot-plug fully.
10. **Privacy.**
    - The descriptor's privacy class is `operator_room`.
    - `entity_selectable` defaults to false for that class, and the operator opts in per source.
    - On the reference host the CTO opted in on 2026-11-01: the entity may see the room, and may choose the webcam itself. So that host's operator configuration sets `entity_selectable = true` for its webcam source.
    - The run manifest records the opt-in as a label (`consent = "operator"` with its date).
    - The entity's choice still passes every gate of `perceptual-locus-switching`.
    - The by-id name carries the camera's serial number, so records keep a 16-hex SHA-256 prefix of it. The by-id name itself is never recorded.
    - The zero-persistence invariant (`tests/test_zero_persistence_invariant.py`) extends to every new file.
    - The preview stays dev-gated (`KAINE_PERCEPTION_PREVIEW`).

### D5. The MuJoCo source

1. The world object is shared.
   - One `SimWorld` per source owns `MjModel` and `MjData`, built from the body model that `virtual-world-body` declares.
   - The perceptual source renders the body's named camera. The embodiment adapter reads proprioception and applies commands to the same object, in process.
2. Rendering is headless.
   - `MUJOCO_GL=egl` is set before import, and `mujoco.Renderer(model, height, width)` with `update_scene(data, camera=<name>)` renders to an (H, W, 3) uint8 array, converted to BGR for the capture loop as the screen source does.
   - osmesa does not work on this host. Without EGL the source is unavailable and the boot refuses. It never falls back to glfw, which needs a display.
3. The GPU plan. GPU 0 (RTX 4070 SUPER, 12 GB) hosts the language organ. GPU 1 (RTX 3070, 8 GB) hosts the vision encoder.
   - The renderer goes on GPU 1, through `MUJOCO_EGL_DEVICE_ID`.
   - The rendered array is consumed by the encoder on the same card. Physics runs on the CPU.
   - A 640×480 scene at 10 Hz is small next to the encoder, but this is measured, not assumed. The preboot device map gains a `sim_render` entry, and the boot's resource check measures the render's VRAM and time per frame on the configured card and refuses past a configured limit.
   - EGL device indexes need not equal CUDA indexes. The preflight maps them by the EGL device's PCI bus id and refuses on a mismatch.
4. Stepping.
   - The world steps on entity time (`EntityClock`), so time dilation reaches it.
   - It holds while the source is not selected, and while sleep or a freeze holds the clock. The world waits, as the programme does.
5. No audio. MuJoCo has no audio facility: no audio sensor type in `mjtSensor` and no audio API in the package (checked in 3.16.0). The source declares no audio modality.
   - The welfare observer reads the selected source's declared modalities. It records a declared-absent modality as `modality_absent` rather than raising a silent-sensor advisory.
   - A sound model for the simulated world (contact impulses rendered as sound) is a new sense. It needs its own design and a second review, and is not part of this change.

### D6. Network sources

- **`stream`.** A game streamed from a Sunshine host, received by a Moonlight-protocol client helper. Design is in `virtual-world-body` D7.
  - The host is this desktop under that change's GPU arbitration rule, or another of the CTO's machines. The CTO decided on 2026-11-01 not to wait for the Steam Deck.
  - Video and audio come in process as raw frames and PCM, over a socketpair from the helper.
  - Privacy class `confined_world`, provenance `live`.
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
- **The runtime gate.**
  - `kaine/egress.py` builds one `EgressGate` per adapter from its declaration.
  - The adapter's connector calls the gate before every connection, and connects only to the address the gate resolved and checked.
  - An undeclared host, port or direction is refused, logged with the endpoint label, and raised as an operator advisory.
  - A helper process (the Moonlight client, a .NET world client) receives its endpoints from the launcher, which checks them against the same declaration.
- **Typed outbound messages.** An adapter's send path accepts only the typed messages of its declared classes (`GamepadState`, `AvatarAction`, `OwnSpeech`, `ProtocolControl`), so a raw buffer cannot be handed to it. A static test checks the send signatures.
- **Placement.**
  - Network-capable code for sources and bodies lives only in the adapter packages that declare egress (`kaine/perceptual_sources/network/`, `kaine/modules/embodiment/adapters/<name>/`), or in separate helper programs under `tools/`.
  - The guard test gains a rule: elsewhere in `kaine/modules/`, a socket, `asyncio.open_connection`, `websockets`, `av.open` on a URL, or `cv2.VideoCapture` on a URL is refused. The existing clients of KAINE's own services are the exception.
  - Every client, adapters included, keeps `trust_env=False`. A proxy is an undeclared host.
- **Module internals stay no-cloud.**
  - At boot, every module-internal service URL (the organ, speech, STT, Qdrant, the decision server) must resolve to a loopback, private, container-network or tailnet address. A globally routable address is a named boot refusal.
  - This makes the existing rule structural.
- **Records.**
  - The run manifest lists each declared endpoint by label, scheme, port and outbound classes.
  - A tailnet peer or private host name is hashed, because host names can be personal. A public world host is recorded as declared.
- **Inbound is perception.** What arrives from a network source is perceived like any input: never persisted. In-world text is data, never a command (the salvaged `inbound-world-safety` rule, `virtual-world-body` D8).

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
