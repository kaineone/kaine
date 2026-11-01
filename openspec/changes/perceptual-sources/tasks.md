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

## 3. Device source (one PR)

- [ ] 3.1 Discovery by by-id name, sysfs name and sounddevice name; the `VIDIOC_QUERYCAP` capture check through `fcntl`; loopback refusal; the availability states and their operator messages. Tests: a fake sysfs tree and ioctl. A real-loopback test (the OBS camera) runs in the slow lane.
- [ ] 3.2 Warm-up settling, with the discarded-frame count. Tests: a synthetic brightening stream.
- [ ] 3.3 Loss and fallback through the operator path. Tests: unplug simulation, grace period, no automatic reselection.
- [ ] 3.4 Container passthrough. The preflight resolves the by-id node and the ALSA card into the cycle service (`devices`, `group_add`), names the hot-plug limit, and refuses a missing device with a clear message. Tests: the preflight's generated override for a fake device.
- [ ] 3.5 The zero-persistence static test extended to the new files, and identity hashing in the manifest. Test: `tests/test_zero_persistence_invariant.py`.
- [ ] 3.6 An entity-free check on the real webcam and the USB microphone on a branch: open, settle, hot-plug, busy. No frames kept.

## 4. MuJoCo source (with `virtual-world-body` stage 1)

- [ ] 4.1 `SimWorld`, the EGL renderer on the configured card with the PCI-bus mapping, the resource-limit check, stepping on entity time, and the hold. Tests: headless render shape, hold equality, refusal without EGL.
- [ ] 4.2 The declared-absent audio, and the welfare observer's `modality_absent`. Tests: no silent-sensor advisory while the simulation is selected.

## 5. Declared egress (one PR, before any networked source or body)

- [ ] 5.1 `kaine/egress.py`: the declaration, the closed outbound classes, the `EgressGate` with resolve-then-check, refusals logged and raised as advisories. Tests: an undeclared host, a port outside the range, a redirect to another host, a direction mismatch.
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
