## 1. Design

- [x] 1.1 Research:
  - `kaine-research/sensors-bodies-locus-research-2026-11-01.md`: body schema, latency, ownership, sim-to-real, robot models, ros2_control, game streaming and licences, existing worlds and their rules;
  - the old OpenSimulator body's history (`932e4f45`, `d87f61c8`).
- [x] 1.2 The descriptor, per-body channels, the MuJoCo adapter, latency, the sequencing with `embodiment-motor-contingency`, the game stream, the existing worlds (later) and the welfare rules (proposal, design, specs).
- [x] 1.2a The CTO's answers of 2026-11-01:
  - the JetHexa as the default body (D4), from the product data and the vendor's public source; a licensed model does not exist, so KAINE builds its own;
  - games re-sequenced, with Tailnet Lock, ACLs and same-host GPU arbitration (D7);
  - online worlds through declared egress (D8).
- [ ] 1.3 The CTO's OK for each dependency:
  - the `sim` extra (`mujoco==3.16.0`, already installed);
  - for the game stage: moonlight-common-c and FFmpeg in the separate helper;
  - for the world stage: LibreMetaverse or Hippolyzer, and Firestorm.
- [ ] 1.4 Apply the amendments of design D6 to `embodiment-motor-contingency`: its start condition (the simulated JetHexa, stage J1), and task 2.4 as the real JetHexa adapter.

## 2. J0: the simulated JetHexa (after `embodiment-held-status` and `perceptual-sources` 2.x)

- [ ] 2.1 `BodyDescriptor` on `EmbodimentCapabilities`, per-body channels and ranges, the `expose` list, and stages from the body. Tests: extend `tests/test_embodiment_module.py` and `tests/test_embodiment_control_surface.py` (stub unchanged, clamp to declared ranges, a misspelled name refused).
- [ ] 2.2 `kaine/sim/world.py` (`SimWorld`), and the `mujoco` adapter: actuators, lag, delay, sensor delay, injected noise. Tests: a step response within delay and lag, noise statistics, writes to exposed channels only.
- [ ] 2.3 The provisional JetHexa MJCF of KAINE's own, with its model card:
  - 18 leg joints with HX-35H limits;
  - the pan-tilt head and camera;
  - the IMU;
  - sphere feet;
  - the bus-rate loop with the modelled read delay;
  - depth and lidar declared but not wired; temperature and voltage absent.

  No vendor files. Tests: the model compiles; five-leg stance is statically stable; joint channels only (no gait channel).
- [ ] 2.4 Domain randomisation from a body seed drawn once per entity, persisted with it, carried by preservation bundles, copied to forks, and recorded in the manifest; re-randomisation only as a recorded operator act. Tests: the same body across two boots of one entity; a fork has its parent's body; ranges respected.
- [ ] 2.5 Latency measured on a cloned simulation state, never on the occupied body, plus the passive measure from the entity's own commands; the bound in entity time. Tests: a configured delay is measured within tolerance; the occupied body's joints are untouched by the probe; the bound refuses.
- [ ] 2.6 Source gating, the world holding while away, and operator reset. Tests: no effect while another source is selected; reset recorded with the operator as initiator.
- [ ] 2.6a Frozen or omitted position channels hold the current position (velocity and effort go to 0), and motor feedback is built from the body descriptor. Test: a frozen position joint does not move over 1,000 ticks.
- [ ] 2.6b The instability detector (warning counters, non-finite state) and the stuck detector, with advisory, hold, and fallback to the programme (`body_stuck`, `sim_unstable`); escalation in unattended runs. Tests: an injected non-finite state; a wedged body under commands.
- [ ] 2.6c Asset confinement: MJCF loads only from the vendored asset directory, refusing absolute paths and `..`; textures procedural or vendored. Tests: an include outside the directory is refused.
- [ ] 2.7 Touch without valence, and a static check that no pain, damage or injury signal exists in the body package. Test: `tests/test_sim_body_no_nociception.py`.
- [ ] 2.8 With `embodiment-motor-contingency` 2.1-2.3: the driving loop, the learner and the motor report against the simulated JetHexa, stages J1-J2; `embodiment_built()` true only with both. Tests are that change's, run against the simulated head.

## 3. J3-J4, the measured model and the real robot

- [ ] 3.1 J3 and J4 as body stages, each joined on demonstrated competence.
- [ ] 3.2 When the robot is built:
  - measure link lengths, axes and part masses;
  - identify each servo (step responses at the bus rate) and the foot friction;
  - update the model card, marking each value measured or identified.
- [ ] 3.3 Inspect the robot's ROS 2 Humble stack: topics, services, and whether per-joint commands and joint state are exposed. Record it in the docs.
- [ ] 3.4 The real JetHexa adapter behind the same descriptor: a ROS 2 bridge, or a thin on-robot bridge over a declared tailnet endpoint. Tests: a protocol-level fake of the bus or topics. Then one supervised hardware check, entity-free.
- [ ] 3.5 Optional, if Hiwonder grants written permission: convert its 2027 description package with MuJoCo's URDF loader, then apply the hand-added items of design D4.

## 4. Games (after J1-J2 for acting; helper and host in parallel with J0)

- [ ] 4.0 Same-host spike: a separate display that Sunshine captures (gamescope headless or a second X server), and a gamepad visible only to the game's container. Until it passes, same-host sessions are refused and the host is another machine.
- [ ] 4.1 `kaine-moonlight-helper` in its own repository, as a separate GPL-3.0 program with its own LICENSE: pairing, the stream through moonlight-common-c, FFmpeg decode, and the socketpair message set. Tests: message framing; no disk writes (static check plus a run under a read-only filesystem).
- [ ] 4.2 The launcher's checks. Tests: each refusal.
  - Tailnet Lock (`tailscale lock status`, parsed and tested against captured output);
  - the host's ports;
  - the host encryption setting;
  - latency, probed before the session with no entity attached;
  - the declared egress, behind the nftables allowlist with escape probes;
  - host confinement: curated application list, keyboard and mouse off, Steam offline with notifications off, internet blocked except the tailnet, a confined session;
  - continuous path monitoring.
- [ ] 4.3 Read Valve's subscriber agreement and each listed title's terms on automated play. Record the result in the curated-list docs before the first session.
- [ ] 4.4 The `game_pad` body with its declared channels (no Guide, home or share channel) and per-title contexts, and the curated title list. Tests: no channel mapping in code (static check), contexts per title, and a helper message set with no keyboard, mouse or text type.
- [ ] 4.5 Same-host GPU arbitration: admission through NVML, the priority bands, ending before sleep. Tests: fake NVML readings for each rule.
- [ ] 4.6 The listener preflight and the tailnet ACL template in the docs. Tests: a listener on `0.0.0.0` refused.
- [ ] 4.7 Independent second review, and a supervised session with a game host.

## 5. Existing worlds (later, each its own change)

- [ ] 5.1 A local OpenSimulator region with a headless client adapter, reusing the salvaged framing, verb table, inbound-world-safety rules and tests from `932e4f45^` and `d87f61c8^`.
- [ ] 5.2 Vision there through a viewer (Firestorm with LEAP), if the entity is to see in that world.
- [ ] 5.3 Hypergrid destinations, each grid's rules on bots read first, through declared egress.
- [ ] 5.4 Second Life: a separately registered account flagged on the Scripted Agent Status page, and the policies of design D8, re-read before the change.
- [ ] 5.5 Paracosmic, once its transport exists.

## 6. Docs and review

- [ ] 6.1 `docs/09-modules/embodiment.md` and `docs/20-embodiment-adapters.md` (the descriptor, the MuJoCo adapter, what is held), and the `config/kaine.toml` comments.
- [ ] 6.2 Independent second review of every PR (a new body), and a supervised validation boot on a branch before any body joins an entity.
- [ ] 6.3 `openspec validate virtual-world-body --strict`.
