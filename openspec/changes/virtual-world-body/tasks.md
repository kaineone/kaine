## 1. Design

- [x] 1.1 Research:
  - `kaine-research/sensors-bodies-locus-research-2026-11-01.md`: body schema, latency, ownership, sim-to-real, robot models, ros2_control, game streaming and licences, existing worlds and their rules;
  - the old OpenSimulator body's history (`932e4f45`, `d87f61c8`).
- [x] 1.2 The descriptor, per-body channels, the MuJoCo adapter, the three bodies, latency, the sequencing with `embodiment-motor-contingency`, the game stream (held), the existing worlds (later) and the welfare rules (proposal, design, specs).
- [ ] 1.3 The CTO's OK for each dependency:
  - the `sim` extra (`mujoco==3.16.0`, already installed);
  - vendoring the Menagerie SO-101 model with its Apache-2.0 licence;
  - for the game stage: moonlight-common-c and FFmpeg in the separate helper;
  - for the world stage: LibreMetaverse or Hippolyzer, and Firestorm.
- [ ] 1.4 Apply the amendments of design D6 to `embodiment-motor-contingency`: its start condition, and task 2.4 as the later real adapter.

## 2. B1: the simulated pan-tilt head (after `embodiment-held-status` and `perceptual-sources` 2.x)

- [ ] 2.1 `BodyDescriptor` on `EmbodimentCapabilities`, per-body channels and ranges, the `expose` list, and stages from the body. Tests: extend `tests/test_embodiment_module.py` and `tests/test_embodiment_control_surface.py` (stub unchanged, clamp to declared ranges, a misspelled name refused).
- [ ] 2.2 `kaine/sim/world.py` (`SimWorld`), the pan-tilt MJCF from the `dynamixel_2r` template with its MIT licence, and the `mujoco` adapter: actuators, lag, delay, sensor delay, injected noise. Tests: a step response within delay and lag, noise statistics, writes to exposed channels only.
- [ ] 2.3 Domain randomisation from the run seed, recorded in the manifest. Tests: seeded determinism, ranges respected, fixed within a run.
- [ ] 2.4 Latency measurement and the bound. Tests: a configured delay is measured within tolerance, and the bound refuses.
- [ ] 2.5 Source gating, the world holding while away, and operator reset. Tests: no effect while another source is selected; reset recorded with the operator as initiator.
- [ ] 2.6 Touch without valence, and a static check that no pain, damage or injury signal exists in the body package. Test: `tests/test_sim_body_no_nociception.py`.
- [ ] 2.7 With `embodiment-motor-contingency` 2.1-2.3: the driving loop, the learner and the motor report against B1; `embodiment_built()` true only with both. Tests are that change's, run against the simulated head.

## 3. B2 and B3

- [ ] 3.1 B2: the SO-101 arm with gripper and wrist camera, vendored with its licence; body stages for the arm. Joined after B1's curriculum shows competence.
- [ ] 3.2 B3: the differential-drive base under the arm, with velocity wheels and its own stages.

## 4. Games (held until the Steam Deck is on the tailnet)

- [ ] 4.1 `tools/kaine-moonlight-helper/` as a separate GPL-3.0 program with its own LICENSE: pairing, the stream through moonlight-common-c, FFmpeg decode, and the socketpair message set. Tests: message framing; no disk writes (static check plus a run under a read-only filesystem).
- [ ] 4.2 The launcher's checks: tailnet peer, direct path, host encryption setting, latency. Tests: each refusal.
- [ ] 4.3 Read Valve's subscriber agreement and each listed title's terms on automated play. Record the result in the curated-list docs before the first session.
- [ ] 4.4 The `game_pad` body with its declared channels and per-title contexts, and the curated title list. Tests: no channel mapping in code (static check), contexts per title.
- [ ] 4.5 Independent second review, and a supervised session with the Deck.

## 5. Existing worlds (later, each its own change)

- [ ] 5.1 A local OpenSimulator region with a headless client adapter, reusing the salvaged framing, verb table, inbound-world-safety rules and tests from `932e4f45^` and `d87f61c8^`.
- [ ] 5.2 Vision there through a viewer (Firestorm with LEAP), if the entity is to see in that world.
- [ ] 5.3 Hypergrid destinations, each with its operator's permission and the CTO's decision.
- [ ] 5.4 Second Life: a separate scripted-agent account and the policies of design D8, re-read before the change.
- [ ] 5.5 Paracosmic, once its transport exists.

## 6. Docs and review

- [ ] 6.1 `docs/09-modules/embodiment.md` and `docs/20-embodiment-adapters.md` (the descriptor, the MuJoCo adapter, what is held), and the `config/kaine.toml` comments.
- [ ] 6.2 Independent second review of every PR (a new body), and a supervised validation boot on a branch before any body joins an entity.
- [ ] 6.3 `openspec validate virtual-world-body --strict`.
