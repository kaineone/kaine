## Why

The CTO set the project's point on 2026-11-01: a mind that senses the world through whatever sensors are attached, thinks about what it receives, and acts through whatever actuators are connected. A basic version should switch between the media feed, a USB webcam, and a virtual world (a MuJoCo simulation or a video game).

Today a KAINE entity has exactly one source per run, fixed at boot by `[perception_feed].mode`: `off`, `seeded`, `playlist`, `stimulus_source`, `live` or `screen` (`kaine/boot/perception_feed.py:545-623`). The perceptual locus picks a world class (`physical`, `virtual` or `off`, `kaine/perception_state.py:49`) but not a source within it. So there is nothing for the locus to choose between, and the module that applies a switch is a documented no-op (`docs/09-modules/perceptual-locus.md`, "Status"). A new kind of sensor has nowhere to plug in except as a new feed mode wired by hand.

The research note (`kaine-research/sensors-bodies-locus-research-2026-11-01.md`) gives three findings this change is built on:

- **A sense is weighted by its reliability.** Ernst and Banks 2002; Alais and Burr 2004.
- **A sense is defined by its laws of sensorimotor contingency, not by its channel.** O'Regan and Noë 2001; Seth 2014.
- **The brain keeps context-specific models selected by a contextual cue.** Wolpert and Kawato 1998; Haruno, Wolpert and Kawato 2001. That needs a stable identity for each source.

So each source needs a declared identity, modalities, rate, privacy class and provenance, and the system needs a single place that knows what is attached and whether it is available.

### What already exists (audit, origin/main d7fabdc0)

- **Video source contract.** The capture loop takes a pluggable `_VideoSource` (`open`, `read`, `release`; `kaine/modules/vision/live.py:42-45`). It is built per open from a `source_factory(device, *, width, height)` (`live.py:301-310`).
- **Source changes.** The capture loop closes the source when its desired reader turns false and reopens it when the reader turns true (`live.py:256-276`). The microphone loop has the same shape (`kaine/modules/audition/live.py:261-330`).
- **Feed builders.** Boot builds a video factory per feed mode (`kaine/boot/perception_feed.py:545-623`), a screen factory (`perception_feed.py:626-687`), a desktop-monitor audio factory (`perception_feed.py:690-722`) and audio factories per mode (`perception_feed.py:724-...`).
- **USB webcam.** OpenCV's `cv2.VideoCapture(device)` opens it (`live.py:92-133`), with `[vision].capture_device = 0` as an index or URL (`config/kaine.toml:570`).
- **USB microphone.** sounddevice opens it, with `[audition].capture_device = ""` meaning the OS default (`kaine.toml:1029`).
- **Locus binding.** Vision binds the real camera to the `physical` locus and any configured factory to `virtual` (`kaine/modules/vision/module.py:382-411`).
- **Per-run descriptor.** A content-free descriptor of the feed is recorded in the run manifest (`perception_feed.py:930-1069`). For a window it records a hash of the title, never the title.
- **Welfare.** The welfare observer already raises operator advisories when a processor's readings stay undefined or the processor goes silent (`kaine/lifecycle/welfare_signal.py:165-185`).
- **Remote bridge.** The bridge carries a phone's camera and microphone as `remote` input, labelled as an operator channel (spec `remote-bridge`).
- **MuJoCo.** MuJoCo 3.16.0 (Apache-2.0) is installed in the venv. The CTO verified headless rendering with `MUJOCO_GL=egl`; osmesa does not work on this host. `MUJOCO_EGL_DEVICE_ID` selects the GPU (`mujoco/egl/__init__.py:38`, checked in the installed package).

### What is missing

- **No registry.** No descriptor says what a source is: modality, shape, rate, privacy class, live or recorded. None says whether it is available now, or whether the entity may choose it.
- **Webcam handling.**
  - No device identity beyond an index. Indexes move when devices are re-plugged.
  - No hot-plug handling.
  - No refusal of a loopback device standing in for a camera. On this host `/dev/video0` is the OBS virtual camera, `v4l2 loopback`.
- **No simulated world as a source.**
- **Screen capture is not confined.** It grabs the operator's display, region by region (`kaine/modules/vision/screen.py:81-146`). On X11 a region capture can include any window that overlaps it.
- **No seam for scalar or vector sensors.** Temperature, radiation, soil moisture and similar streams have no way in.

## What Changes

1. **A perceptual-source registry.**
   - It is built at boot from `[perceptual_sources]` and ships off.
   - Each source is a declared, content-free descriptor: an id, a kind, its modalities with shape and rate, a locus class (`physical` or `virtual`), a privacy class, a provenance (`live`, `recorded`, `synthetic` or `simulated`), whether the entity may select it, and an optional paired body.
   - The registry probes each source's availability.
   - It hands the vision and audition capture loops one switching factory that opens the selected source's surface.
   - With the registry off, boot builds exactly what it builds today.
2. **The programme source.** It wraps the existing feed modes (`seeded`, `playlist`, `stimulus_source`) without changing them. While another source is selected, the playlist clock is held by an `away` holder, so the programme waits for the entity as it does for sleep and freezes.
3. **The device source: a USB webcam and a USB microphone.**
   - It reuses OpenCV and sounddevice.
   - The camera is opened by stable identity (a `/dev/v4l/by-id` path or a sysfs name substring) and the microphone by name substring, with an index accepted as a fallback.
   - Availability is polled from sysfs, so the source tolerates hot-plug.
   - The capture capability is checked by the VIDIOC_QUERYCAP ioctl through the standard library.
   - A loopback device is refused unless the operator allows it, for testing.
   - An absent device makes the source unavailable and is never silently replaced. An absent initial source is a named boot refusal.
   - Losing the selected source returns the entity, after a grace period, to the configured fallback source.
4. **The MuJoCo source.**
   - The camera named by a simulated body (`virtual-world-body`) is rendered headless through EGL on the GPU named in the device map, to an in-memory array.
   - The simulation steps on entity time, and holds while it is not selected or while sleep or a freeze holds the clock.
   - MuJoCo has no audio. The source declares no audio modality, and the welfare observer reads that declaration rather than raising a silent-sensor advisory.
   - The paired body shares the same in-process world.
5. **Network sources, declared now so the registry's shape fits them.**
   - A game stream (`virtual-world-body`: a Moonlight-protocol client to a Sunshine host over the tailnet). It does not wait for the Steam Deck. The host is this desktop under the GPU arbitration rule, or another of the CTO's machines on the tailnet (CTO, 2026-11-01).
   - An online media stream (`network_media`): an operator-declared URL, such as a live broadcast, decoded by PyAV in memory.
   - Existing worlds reached through a body adapter: OpenSimulator and Hypergrid grids, Second Life, and Paracosmic. Later.
6. **Screen capture of the operator's desktop.** It is registered with privacy class `operator_desktop` and can never be selected by the entity. The existing `mode = "screen"` keeps working as the operator's explicit choice.
7. **A scalar-sensor seam, designed now and built later.**
   - A source declares named channels (unit, range, rate).
   - The seam builds a processor instance per source, with its own forward model, prediction error and report, in the same shape as the other processors.
   - The reference plan is a USB serial board streaming newline-delimited JSON readings.
8. **Declared egress.**
   - The CTO clarified on 2026-11-01 that the no-cloud rule covers KAINE's modules using cloud services. It does not restrict where perceived streams come from, or where the entity's outputs go.
   - So a source or body adapter that reaches a network declares each endpoint and the closed classes of data it may send there.
   - Each networked adapter runs in its own process behind a network boundary that allows only its declared endpoints: a network-less sandbox given checked sockets, or a dedicated user with an outbound allowlist. Escape probes at boot prove it.
   - Module internals stay no-cloud. The proxy guard of `local-service-clients` (#400) stays, and a boot check refuses a public address for any module-internal service URL.
9. **Zero persistence, extended to every new source.**
   - No frame, sample or reading is written anywhere.
   - Device names, which can carry serial numbers, are recorded only as hashes.
   - The static persistence test covers the new files.

## Capabilities

### New Capabilities

- `perceptual-sources`: the registry and descriptor, the programme, device and MuJoCo sources, the network sources (stream, online media, worlds), the declared egress, the confinement rule for desktop capture, the scalar seam, availability, fallback, and the off switch.

### Modified Capabilities

- `perceptual-locus`: the single desired-state model (`source` and off-holders, the derived locus, one locked writer path, today's writers moved onto it, every modality closed while off). It moved here from `perceptual-locus-switching` (re-review R-PS-1).
- `perception-feed`: sleep holds perception off through its off-holder, without touching the source.

Selection among sources by the entity is `perceptual-locus-switching`. The simulated body is `virtual-world-body`.

## Impact

- **Code.**
  - New package `kaine/perceptual_sources/` (descriptor, registry, availability probes, the switching factories). It goes on the import-boundary contract's core list in `pyproject.toml` (`[tool.importlinter]`).
  - `kaine/modules/vision/live.py` and `kaine/modules/audition/live.py`: the source epoch in the desired reader.
  - `kaine/modules/vision/module.py` (`_build_default_live_camera`, locus gate from the selected source).
  - `kaine/boot/perception_feed.py` and `kaine/boot/registry.py`: registry construction, the programme source, the `away` holder.
  - `kaine/modules/vision/feed.py` (the holder name).
  - `kaine/lifecycle/welfare_signal.py` and the welfare observer (declared-absent modalities).
  - `kaine/evaluation/observers/research_event_observer.py` (availability events in the allowlist).
  - `kaine/dashboard/perception.py` (the source list and availability, read-only).
  - `config/kaine.toml` (`[perceptual_sources]`, off).
  - A new `kaine/egress.py` (the declaration, the sandbox arguments, the generated nftables allowlist, the escape probes), and an extension of the guard test `tests/test_local_clients_ignore_proxies.py`.
  - `Dockerfile` (`libegl1` with the glvnd NVIDIA ICD) and `compose/kaine.yml` (graphics driver capability, both GPUs mapped, the resolved device nodes).
  - `kaine/perception_state.py` and `kaine/modules/sleep/module.py`: fail to the programme, never to the room, with the registry on.
- **Dependencies.** None new for the programme and device sources. MuJoCo is already installed. Adding it to `pyproject.toml` as an optional extra (`sim`, `mujoco==3.16.0`, Apache-2.0) needs the CTO's OK, as every new dependency does.
- **Docs.**
  - New `docs/09-modules/perceptual-sources.md`.
  - `docs/09-modules/vision.md`, `docs/09-modules/audition.md`, `docs/09-modules/perceptual-locus.md`.
  - `docs/appendix-a-configuration/perception-and-sleep.md`.
- **Behaviour.** None with `[perceptual_sources].enabled = false`, which is how it ships. Off equals absent, checked against a golden digest captured on origin/main.

## Dependencies and start condition

- **None.** The programme and device sources can be built now. The MuJoCo source is built together with the first simulated body of `virtual-world-body`, because the camera belongs to the body.
- **USB webcam.** The CTO will attach one shortly. Until then the OBS virtual camera (`v4l2 loopback`) stands in, with `allow_loopback = true`, for tests only.
- **Before any entity uses a new source.**
  - An independent second review of the build.
  - The welfare net on.
  - For the webcam: a webcam sees the operator's room. The CTO consented on 2026-11-01 to the entity seeing the room and choosing the webcam itself, and the run manifest records the opt-in.
