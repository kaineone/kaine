## 1. Design

- [x] 1.1 The research note: `kaine-research/sensors-bodies-locus-research-2026-11-01.md`, sections 1-4 and 9-10.
- [x] 1.2 The descriptor, registry, programme, device and MuJoCo sources, the held kinds and the scalar seam (proposal, design, spec).
- [x] 1.3 Prior work cited and built on:
  - `2026-05-21-live-perception` and `2026-06-25-unified-perception-feed` (the capture loops and factories);
  - `2026-09-08-remote-perception-bridge`;
  - `2026-10-03-nexus-perception-availability`;
  - the perceptual locus (spec `perceptual-locus`);
  - `interest-goal-factor` (#557);
  - the welfare blind and silent advisories.
- [ ] 1.4 The CTO's OK for the `sim` optional extra (`mujoco==3.16.0`, Apache-2.0), and later for `pyserial` (BSD-3-Clause) when the scalar seam is built.

## 2. Registry (one PR)

- [ ] 2.1 `kaine/perceptual_sources/` with the descriptor, validation and boot refusals, and the switching factories with the source epoch. Add the package to the import-boundary core list in `pyproject.toml`. Tests: `tests/test_perceptual_sources_registry.py`.
- [ ] 2.2 The programme source and the `away` holder on the playlist clock. Tests: extend the playlist clock tests (holder combination, end of programme unchanged).
- [ ] 2.3 Off equals absent: a seeded, entity-free harness digest against a golden captured on origin/main. Test: `tests/test_perceptual_sources_disabled_identity.py`.
- [ ] 2.4 Availability and selection events, and the research-event allowlist. Tests: allowlist exactness, plus no device identity in any event.
- [ ] 2.5 Classes derived from the kind; a configured class refused. Tests: a device declared virtual refused; a screen source made selectable refused.
- [ ] 2.6 Fail to the programme. Tests: a corrupt file, a missing key, an unknown id and a failed sleep read each resolve to the programme, and no device opens.
- [ ] 2.7 The epoch state machine, physical surfaces closing first, and the clip-ring and audio-window flush. Tests: release clears the epoch; an absent modality does not loop on open; no clip mixes two sources.
- [ ] 2.8 Fallback validation: the programme only, with an ended programme going through the end-of-programme path.

## 3. Device source (one PR)

- [ ] 3.1 Discovery by by-id name, sysfs name and sounddevice name.
  - The `VIDIOC_QUERYCAP` capture check through `fcntl`.
  - Resolution to `/dev/videoN` with the `bus_info`/`card` re-check before open.
  - The `REQBUFS` busy check, skipped on the held node.
  - Loopback refusal, and the availability states with their operator messages.
  - Tests: a fake sysfs tree and ioctl. A real-loopback test (the OBS camera) runs in the slow lane.
- [ ] 3.2 Warm-up settling (a 10-frame minimum, a luminance floor, the 60-frame cap) with the discarded-frame count. Tests: a synthetic brightening stream, and a near-black start that must not settle early.
- [ ] 3.3 Loss and fallback through the operator path. Tests: unplug simulation, grace period, no automatic reselection.
- [ ] 3.4 Container passthrough. The preflight resolves the by-id node and the ALSA card into the cycle service (`devices`, `group_add`), names the hot-plug limit, and refuses a missing device with a clear message. Tests: the preflight's generated override for a fake device.
- [ ] 3.5 The zero-persistence static test extended to the new files, and keyed (HMAC) identity hashing with the per-install key. Test: `tests/test_zero_persistence_invariant.py`.
- [ ] 3.5a The room approval `KAINE_OPERATOR_ROOM_APPROVED` per part (`camera`, `microphone`, `entity_select`), recorded in the manifest. Tests: the microphone refused while the camera is allowed; no `entity_select`, so not entity-selectable.
- [ ] 3.6 An entity-free check on the real webcam and the USB microphone on a branch: open, settle, hot-plug, busy. No frames kept.

## 4. MuJoCo source (with `virtual-world-body` stage 1)

- [ ] 4.1 `SimWorld` with one owner thread for physics, scene update and rendering.
  - The EGL device chosen by PCI address through the CUDA or DRM attribute.
  - The resource-limit check through NVML graphics processes or the used-memory delta.
  - Stepping on entity time with a wall-rate cap, and the hold.
  - Tests: headless render shape; renders requested from pool threads all run on the owner thread; hold equality; refusal without EGL or without a matching device.
- [ ] 4.1a The container: `libegl1` with the glvnd NVIDIA ICD in the `Dockerfile`, the graphics driver capability and both GPUs in `compose/kaine.yml`. Test: the preflight's check inside the image.
- [ ] 4.1b A `mujoco` source with a body available only when `embodiment_built()` is true; passive views never entity-selectable; the advisory for a long stretch in a source with an absent modality.
- [ ] 4.2 The declared-absent audio, and the welfare observer's `modality_absent`. Tests: no silent-sensor advisory while the simulation is selected.

## 5. Declared egress (one PR, before any networked source or body)

- [ ] 5.1 `kaine/egress.py`: the declaration and the closed outbound classes.
  - The two boundaries: a bubblewrap `--unshare-net` sandbox with passed sockets, and a per-adapter user with a generated nftables allowlist that the operator installs.
  - Escape probes at boot.
  - Tests: an undeclared host, a port outside the range, a direction mismatch, and a redirect through the real FFmpeg path against a local redirecting server.
- [ ] 5.2 Typed send paths, with a static check that a send signature accepts only declared message types.
- [ ] 5.3 The guard test's placement rule: sockets, websockets, or URL opens by PyAV or OpenCV outside declared adapter packages are refused. Exercise each rule with a throwaway probe file, as #400 did.
- [ ] 5.4 The boot check that module-internal service URLs are not globally routable. Tests: loopback, compose, tailnet and private addresses pass; a public address refuses.
- [ ] 5.5 Manifest records for endpoints, with private and tailnet host names hashed.

## 6. Network media (later, small)

- [ ] 6.1 The `network_media` source: a declared URL opened by PyAV in memory, with no cache or recording options. Tests: real-path decode from a local HTTP server, the egress gate on a redirect, and the persistence test.

## 7. Docs and review

- [ ] 7.1 New `docs/09-modules/perceptual-sources.md`. Update `vision.md`, `audition.md`, `perceptual-locus.md` and `docs/appendix-a-configuration/perception-and-sleep.md`. Comment out a `[perceptual_sources]` block in `config/kaine.toml`.
- [ ] 7.2 Independent second review of each PR (a new sense, or a new egress).
- [ ] 7.3 `openspec validate perceptual-sources --strict`.

## 8. Later

- [ ] 8.1 The scalar seam's processor and the USB serial reference source (needs the CTO's OK for `pyserial`).
- [ ] 8.2 A PipeWire camera source, if the camera must be shared with another program.
