## Why

The CTO's direction of 2026-11-01 is a mind that acts "through any kind of actuators connected, be they a virtual avatar, robotic body or something we haven't imagined yet". MuJoCo is the platform for developing KAINE's embodiment layer, and for working out robotic control without a physical robot for now. The CTO set two conditions:

- The simulated body is a robot, not a game avatar. That means realistic actuators, proprioception and timing, and a hardware-shaped interface, so that a real robot later swaps only the adapter.
- The CTO also wants the entity to play games from a Steam library with a controller, and to explore existing virtual worlds (Second Life, OpenSimulator grids through the Hypergrid) and, later, Paracosmic.

The CTO will build a Hiwonder JetHexa (a ROS 2 Humble hexapod with 18 HX-35H bus servos, a pan-tilt head carrying a depth camera, lidar and an IMU), and made it the default body: simulated first, then real.

This change designs the actuator side of all of these through the existing embodiment adapter seam, and puts them in order.

### What already exists, and what is pretend today (audit, origin/main d7fabdc0)

- **The adapter seam is real and small.**
  - `EmbodimentAdapter` has `capabilities`, `open`, `close`, `feed`, `apply_action` and `apply_setpoints` (`kaine/modules/embodiment/adapter.py:111-139`).
  - Its descriptor declares feed kinds, symbolic families, continuous channels and raw-buffer keys (`adapter.py:48-108`).
  - The core gates action by the `virtual` locus and by per-name exposure (`kaine/modules/embodiment/module.py:254-372`).
  - It requires the config flag and `KAINE_EMBODIMENT_OPERATOR_APPROVED=1` (`module.py:71-72`).
- **The only body is pretend.**
  - `StubAdapter` "records what it is asked to do" and reports success for everything (`kaine/modules/embodiment/adapters/stub.py:1-21`, `59-98`).
  - The core then publishes an efference copy with `forwarded: true` for a movement no body made.
  - `embodiment-held-status` (branch `spec/grounding-social-safety-2026-10-31`, design only) makes a reference body a boot refusal and adds `embodiment_built()`.
- **The control surface fits one kind of body.**
  - Five fixed channels for a locomoting avatar (`kaine/modules/embodiment/channels.py`: `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch`, `interact`).
  - Three stages over those channels (`kaine/modules/embodiment/control_surface.py:79-83`).
- **No movement is ever produced or learned.**
  - The only policy emits nothing (`QuiescentMotorPolicy`, `control_surface.py:184-195`).
  - Nothing drives the surface per tick.
  - `embodiment-motor-contingency` (design only) designs the driving loop, the learner and a pan-tilt camera as the first body. The CTO's direction makes that body a simulated one first.
  - Without that learner, no body in this change does anything useful. It would be a body the entity cannot yet move.
- **The old OpenSimulator body.**
  - It was a forked Firestorm viewer with a LEAP plugin, wired to a TCP and MessagePack bridge.
  - It was removed in `932e4f45` (#31, 2026-07-10), and its references were purged in `d87f61c8` (#37).
  - What survives as reusable is listed in design D9. The old connector is obsolete for Paracosmic, which is now a custom three.js program (CTO correction, 2026-11-01).

## What Changes

1. **A hardware-shaped body descriptor.** This is an addition to `EmbodimentCapabilities`, so nothing existing changes. A body declares:
   - its joints, each with command interfaces (`position`, `velocity` or `effort`), state interfaces and limits (range, velocity, effort);
   - its sensors (joint state, IMU, touch or contact, cameras);
   - its control rate and expected latency;
   - its freeze-then-free stages.

   The shape mirrors ros2_control's command and state interfaces (Apache-2.0) without adopting ROS 2 now, so a ros2_control or LeRobot-style real-robot adapter can later sit behind the same seam.
2. **Body-declared channels.**
   - A body may declare its own continuous channels, one per joint command interface, each with its own range.
   - The canonical five-channel vocabulary stays for the bodies that use it.
   - Exposure keys are routed by the declared names, as `embodiment-exposure` already requires.
3. **The MuJoCo adapter.** It shares the in-process `SimWorld` with the `mujoco` perceptual source of `perceptual-sources`.
   - Position servos with gains and force limits taken from real servos.
   - Actuator lag and delay, and sensor delay. These are applied by MuJoCo.
   - Sensor noise injected by the adapter. MuJoCo stores a sensor's `noise` but does not apply it, which the research pass checked by running the installed 3.16.0.
   - A control rate of 50-200 Hz over a 2-5 ms physics step.
   - Domain randomisation from a body seed drawn once per entity and kept with it as part of its body identity: masses, damping, friction, gains, latency, noise and textures, within attributed ranges from the sim-to-real literature, and recorded in the manifest.
   - A command-to-feedback latency measured on a cloned simulation state, never by moving the occupied body, recorded and bounded.
   - Frozen or omitted position joints hold their position.
   - One owner thread for the world.
   - Assets confined to the vendored directory.
   - It acts only while its own source is selected.
4. **The default body: the JetHexa.**
   - **The model is KAINE's own MJCF.** Hiwonder's repository has no licence, describes the older edition, and gives its links placeholder masses. So the MJCF is built from published dimensions first, and from the built robot's measurements and system identification after.
   - **Timing matches the real servo bus.** Its interfaces and control rate match the real servo bus: position commands and position feedback at about 20 Hz for all 18 joints at 115200 baud.
   - **The real adapter** later bridges to the robot's ROS 2 stack, or to a thin on-robot bridge, behind the same descriptor.
   - **The curriculum** is body-declared stages:
     - J1, head pan;
     - J2, pan and tilt;
     - J3, one leg at a time while five legs stand;
     - J4, all legs.

     The pan-tilt head stays the first motor-learning step because it is the smallest body with lawful contingencies. It is the JetHexa's own head, so nothing is learned for a body that will never exist.
   - **Not scheduled.** The SO-101 arm (Apache-2.0) and a wheeled base remain documented alternatives.
   - No Meta-owned model, asset or tool.
5. **Sequencing with `embodiment-motor-contingency`.** That change's driving loop, learner and motor prediction-error report are built against the simulated JetHexa, from stage J1. Its start condition is amended accordingly: the hardware stage no longer gates development, under the CTO's 2026-10-31 and 2026-11-01 decisions. `embodiment_built()` turns true only when the MuJoCo body and the driving loop both exist. The body is never pretend.
6. **Welfare of a simulated body.**
   - Proprioceptive and motor prediction errors are the entity's and are watched by the welfare net.
   - Touch reports contact force as touch, with no valence.
   - No simulated pain, damage or injury signal exists, and none may be added without its own design and an independent second review.
   - Instability and a stuck body are detected. Either one returns the entity to the programme, with an advisory, and the operator can reset the body.
7. **Games, without waiting for the Steam Deck** (CTO, 2026-11-01).
   - The entity is a Moonlight-protocol client of a Sunshine host: another of the CTO's machines, or this desktop with one entity at a time.
   - All traffic goes over the tailnet, with Tailnet Lock required and tailnet ACLs restricting what is reachable.
   - Same-host play follows a GPU arbitration rule: admission by measured free memory, the mind's priority, and the session ended before sleep. It also needs a separate display and a confined gamepad, which a spike must prove first.
   - A separate, KAINE-written helper program is licensed GPL-3.0 because it links moonlight-common-c (GPL-3.0). It decodes the stream and passes raw frames, PCM and gamepad state over a socketpair: a simple message set across a process boundary, which the GPL FAQ calls separate programs. KAINE's own code stays under the CAL.
   - The gamepad's axes and buttons are body-declared channels, and their meaning is learned by the motor-contingency learner, not mapped.
   - Offline, single-player titles from an operator-curated list first.
   - The game body acts once the learner exists, after J1-J2.
8. **Existing worlds, later, through the same seam.** Online worlds and outbound actions to them are allowed (CTO, 2026-11-01), through declared egress (`perceptual-sources` D9).
   - A local OpenSimulator region first (BSD-3-Clause), to test with nothing at stake.
   - Then Hypergrid destinations, each grid's bot rules read first.
   - Second Life last: a separately registered scripted-agent account, the scripted-agent policy and the third-party viewer policy followed, and no logging or relaying of residents' chat or details.
   - Paracosmic as its own adapter once its transport exists.

## Capabilities

### New Capabilities

- `embodiment-sim-body`: the hardware-shaped descriptor, the MuJoCo adapter, its realism and randomisation, latency, source gating, operator reset, the welfare rules for a simulated body, and the build status.
- `embodiment-game-stream`: the game-stream body: the helper boundary, the tailnet rules (Tailnet Lock, ACLs, encryption), GPU arbitration for same-host play, latency, the gamepad channels, the title list, zero persistence.

### Modified Capabilities

- `embodiment-exposure`: channels and ranges declared per body.

## Impact

- **Code.**
  - `kaine/modules/embodiment/adapter.py` (a `body` descriptor field) and `channels.py` (per-body ranges).
  - `control_surface.py` (stages from the body).
  - `module.py` (act only while the paired source is selected; per-body channel clamp).
  - New `kaine/modules/embodiment/adapters/mujoco/` (adapter, randomisation, noise, bodies).
  - New `kaine/sim/` for the shared `SimWorld` and the MJCF assets, with Menagerie licence files kept beside the models they cover.
  - `kaine/boot/factories/embodiment.py`.
  - `kaine/evaluation/observers/research_event_observer.py` (proprioception summaries).
  - Later, `kaine-moonlight-helper`: a separate GPL-3.0 program in its own repository, with its own LICENSE, which KAINE refers to and does not contain.
- **Dependencies.**
  - MuJoCo is already installed (3.16.0, Apache-2.0). The `sim` optional extra needs the CTO's OK.
  - The JetHexa MJCF is KAINE's own, so nothing is vendored. Hiwonder's description package would need its written permission.
  - The SO-101 alternative would vendor the Menagerie model (Apache-2.0) with its licence.
  - The game stage adds moonlight-common-c (GPL-3.0) and FFmpeg's decoders (LGPL-2.1+, depending on the build) to the separate helper only. Their installation needs the CTO's OK.
  - The later world adapters would add LibreMetaverse (BSD-3-Clause, .NET sidecar) or Hippolyzer (LGPL-3.0), and for vision a Firestorm viewer (LGPL-2.1). Each needs the CTO's OK.
- **Docs.** `docs/09-modules/embodiment.md`, `docs/20-embodiment-adapters.md`, `config/kaine.toml` comments.
- **Behaviour.** None in any shipped configuration. The embodiment module ships off and the MuJoCo adapter is not the default.

## Dependencies and start condition

- **J0 (the simulated JetHexa).**
  - Needs `embodiment-held-status` merged, so a reference body can never be counted as a body.
  - Needs `perceptual-sources` (registry and the `mujoco` source).
  - Is built together with `embodiment-motor-contingency` 2.1-2.3.
- **J3 and J4** follow demonstrated competence. That is the curriculum, not a calendar.
- **The measured model and the real adapter** follow when the CTO has built the robot.
- **Games.**
  - The helper and the host setup can be built in parallel with J0.
  - The game body acts after J1-J2.
  - It is refused at boot until the checks in `embodiment-game-stream` pass: Tailnet Lock, the host's ports, encryption, latency, and for same-host play the GPU admission and the display and confinement spike.
- **Existing worlds.** Later, each by its own change, behind `perceptual-sources`' declared egress.
- **Before any body joins an entity.** An independent second review of every PR, the welfare net on, a supervised validation boot on a branch, and the operator gate (`KAINE_EMBODIMENT_OPERATOR_APPROVED=1`) kept.
