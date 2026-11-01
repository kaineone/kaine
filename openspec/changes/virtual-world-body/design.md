# Design: bodies for the virtual worlds

## Context

The evidence is in `kaine-research/sensors-bodies-locus-research-2026-11-01.md`: sections 5-8 for the mind's side, and sections 10-13 for engineering, robots, games and existing worlds.

The mind's side:

- **A body is whatever moves predictably when commanded.**
  - Tool use extends the body schema to the tool's tip (Iriki, Tanaka and Iwamura 1996, *Neuroreport* 7:2325-2330; Maravita and Iriki 2004, *Trends Cogn Sci* 8:79-86).
  - A video image of the hand can become part of it (Iriki et al. 2001, *Neurosci Res* 40:163-173).
- **Feedback must arrive in time.** The rubber-hand illusion was strongest below 300 ms of visual delay and gone at 600 ms (Shimada, Fukuda and Hiraki 2009, *PLoS ONE* 4:e6185).
- **Ownership forms within minutes.**
  - A first-person view with synchronous input was enough within 1-2 minutes (Petkova and Ehrsson 2008, *PLoS ONE* 3:e3832).
  - A first-person view alone was enough in Slater et al. 2010 (*PLoS ONE* 5:e10564).
- **Learning a body requires moving it** (Held and Hein 1963, from secondary sources). The body model can be learned from the agent's own movement with no given kinematics:
  - Bongard, Zykov and Lipson 2006, *Science* 314:1118-1121, from secondary sources;
  - Rolf, Steil and Gienger 2010, *IEEE TAMD* 2:216-229;
  - Baranes and Oudeyer 2013, *Robot Auton Syst* 61:49-73.

  Those last three are the developmental-robotics basis of `embodiment-motor-contingency`, together with Kuniyoshi and Sangawa 2006 and Oudeyer, Kaplan and Hafner 2007, which that change cites.
- **Fast control adapts first, and the context of each body is kept separately** (Wolpert and Kawato 1998; Haruno, Wolpert and Kawato 2001). The forward-model contexts of `perceptual-locus-switching` apply to motor models too: one per body.

Sim-to-real (arXiv abstracts read, numbers from the PDFs):

- **Tobin et al. 2017**, arXiv:1703.06907. Visual randomisation alone transferred a detector to within 1.5 cm on real objects.
- **Peng et al. 2018**, arXiv:1710.06537.
  - Randomising link mass (×0.25-4), joint damping (×0.2-20), friction (0.1-5), actuator gains (×0.5-2), observation noise and the action timestep let a MuJoCo policy push a puck on a real arm.
  - Removing the timestep or noise randomisation hurt most.
- **Tan et al. 2018**, arXiv:1804.10332.
  - Ranges: mass 80-120%, motor strength 80-120%, control step 3-20 ms, latency 0-40 ms, contact friction 0.5-1.25, IMU bias ±0.05 rad.
  - Without an actuator model or latency, the controllers "do not work on the real robot".
- **OpenAI et al. 2019**, arXiv:1910.07113. Automatic domain randomisation, including latency and backlash.
- **Zhao, Queralta and Westerlund 2020**, arXiv:2009.13303. A survey.

## Decisions

### D1. A hardware-shaped body descriptor

`EmbodimentCapabilities` gains an optional `body: BodyDescriptor`. Absent means today's behaviour: the stub and symbolic bodies.

| Field | Content |
|---|---|
| `joints` | name; command interfaces from `position`, `velocity` and `effort`; state interfaces; `range`, `velocity_limit` and `effort_limit` |
| `sensors` | name and kind (`joint_state`, `imu`, `touch`, `contact`, `camera`, `rangefinder`); rate; latency |
| `control_rate_hz` | the rate the body accepts commands at |
| `expected_latency_ms` | the command-to-feedback delay the adapter claims, checked by D5 |
| `stages` | the freeze-then-free order: tuples of channel names (Bernstein 1967, as cited in `control_surface.py:72-83`) |
| `reset` | whether the operator can reset the body to its start pose |

Why this shape:

- It is ros2_control's hardware-interface vocabulary: named command and state interfaces per joint, of types position, velocity and effort, and the system, actuator and sensor component roles. `ros-controls/ros2_control` is Apache-2.0, and its `hardware_interface` headers were read.
- `ros-controls/mujoco_ros2_control` (Apache-2.0, maintained, with CI for Jazzy, Kilted, Lyrical and Rolling) puts MuJoCo behind that same interface.
- So a ROS 2 bridge, or a LeRobot-style real-hardware adapter (Hugging Face, Apache-2.0, a `Robot` with `get_observation` and `send_action`, Feetech and Dynamixel buses), later implements the same descriptor, and the entity-side code does not change.

Why not ROS 2 now:

- This host is Fedora-based (Bazzite).
- ROS 2 Lyrical (LTS to May 2031) is Tier 1 on Ubuntu 26.04 and Windows 11, and Tier 2 on RHEL 10. Fedora is not a tier platform (REP 2000 and the Lyrical supported-platforms page, read).
- The stack is C++ and colcon, against KAINE's Python 3.12 venv. Adopting it would add a container and a build system before any body moves.

### D2. Channels declared per body

- A body with a `BodyDescriptor` declares its continuous channels as `<joint>.<interface>`, for example `pan.position` and `tilt.position`, with the joint's range.
- The core clamps each channel to the body's declared range. `CONTINUOUS_CHANNEL_RANGE` (`kaine/modules/embodiment/channels.py`) remains the vocabulary of the canonical five channels and of bodies that use them.
- Exposure keys stay routed by declared names (spec `embodiment-exposure`). For example, `expose_pan.position` becomes `[embodiment.mujoco].expose = ["pan.position", ...]`, because TOML bare keys cannot carry the dot.
- `MOTOR_STAGES` becomes the default for bodies that declare no stages. A body's own `stages` replace it, which is `embodiment-motor-contingency` recommendation 3.

**What an unset channel does depends on its interface** (review VWB-6). Today a frozen channel is sent `0.0`, and a free channel the policy omits is sent `raw.get(name, 0.0)` (`kaine/modules/embodiment/control_surface.py:400-405`). On a position joint that snaps the joint to 0 rad every tick: a movement the entity did not make, on a channel the curriculum calls frozen. So:
- A frozen or omitted `position` channel holds the joint's current measured position at the moment it was frozen, or its last command.
- A frozen or omitted `velocity` or `effort` channel is 0.
- Motor feedback is built from the body descriptor's state interfaces, not from today's avatar-shaped `MotorFeedback` (`control_surface.py:132-170`: forward velocity, heading, gaze, contact). The avatar shape stays for bodies without a descriptor.
- A test pins that a frozen position joint does not move.

The channel names carry no meaning to the entity. `pan.position` is a label for the operator and the records. What a channel does is what the motor forward model learns. Nothing maps a drive or a goal to a joint.

### D3. The MuJoCo adapter

- **The world.**
  - One `SimWorld` (`kaine/sim/world.py`) holds `MjModel` and `MjData`, built from the body's MJCF and a room scene with a few movable objects.
  - It is shared in process with the `mujoco` perceptual source, which renders its camera.
  - One owner thread steps physics, updates the scene and renders, and the adapter reaches it through requests (`perceptual-sources` D5; review PS-6, VWB-9).
- **Time base** (review VWB-9).
  - Physics is paced against `EntityClock`, with a cap on steps per wall second.
  - `control_rate_hz` and `max_latency_ms` are in entity time, with the wall-time figures recorded beside them.
- **Assets are confined** (review VWB-10).
  - MJCF meshes, textures and includes load only from the vendored asset directory. Absolute paths and `..` are refused at load.
  - Randomised textures are generated procedurally or drawn from the vendored set, so a render can never show an operator file.
- **Actuators.**
  - Position servos (`<position>` with `kp`, `kv`, `forcerange`, `ctrlrange`), with gains taken from a real servo. The JetHexa's legs use the HX-35H's force limit and speed (D4), provisional until the real servos are identified. For comparison, the Menagerie SO-101 models its Feetech STS3215 servos with kp 998.22, kv 2.731, forcerange ±2.94 and timestep 0.005.
  - First-order actuator lag through `dyntype="filter"`, a native MuJoCo actuator dynamics type.
  - Actuator command `delay`, native for `general` actuators via `nsample` and `delay`.
  - The research pass read all of these in the XML reference, and the lead checked the dynamics and gain enums in the installed 3.16.0.
- **Sensors.**
  - MuJoCo applies sensor `delay` and `interval`.
  - It does not apply `noise`. It stores the value, and a static joint with `noise=0.5` read with standard deviation 0 in the installed version (research pass, checked by running it).
  - So the adapter adds Gaussian noise itself, at each sensor's declared standard deviation, from the entity's body seed.
- **Rates.**
  - Physics `timestep` 0.002-0.005 s. A control decimation gives `control_rate_hz` between 50 and 200.
  - Matched to hobby servos: Dynamixel's USB latency timer defaults to 16 ms and is advised to be lowered to 1 ms (ROBOTIS e-manual).
  - Delays of 3-20 ms follow Tan et al.'s measured 3 ms servo and 15-19 ms controller latencies.
- **Domain randomisation, drawn once per entity** (review VWB-7, PM decision).
  - **What is sampled:** link masses, joint damping, contact friction, actuator gains, actuator and sensor delays, sensor noise, and material colours and textures of the scene.
  - **Seed.** It is sampled from a body seed created when the entity first meets the body. The seed and the sampled values are persisted with the entity, so they are part of its body identity.
  - **Lifecycle.**
    - A preservation bundle carries them, and a fork copies them.
    - Every run of that entity meets the same body.
    - Re-randomising is an operator act, recorded. It is never a side effect of a reboot. A new body for a persisting entity would change, without any cause in its world, what its motor forward model, which is identity, was trained on.
  - **Ranges, attributed** (review RN-4).
    - Peng et al. 2018, Table I: link mass ×0.25-4; joint damping ×0.2-20; actuator gains ×0.5-2. Their 0.1-5 friction range was the puck's absolute friction, so it is not used as a multiplier. Their observation noise was 5% of each feature's running standard deviation.
    - Tan et al. 2018: mass 80-120%; motor strength 80-120%; latency 0-40 ms; contact friction 0.5-1.25.
    - KAINE narrows each for a first body, and the model card records the ranges used.
  - The sampled values go in the run manifest. They are parameters, not perception.
- **Feeds.**
  - Proprioception (joint positions and velocities, IMU, touch) goes in process to the motor loop of `embodiment-motor-contingency`, at the control rate.
  - The bus gets the summaries the research observer already keeps for `embodiment.proprio`: a position hash and a region label (`kaine/evaluation/observers/research_event_observer.py:469-470`).
  - The camera is the perceptual source's.
- **Efference.**
  - `apply_setpoints` writes `MjData.ctrl` for exposed channels only.
  - It returns true only when the simulation accepted the command at that step.
  - `forwarded: true` is then honest.
- **Source gating.**
  - The adapter acts only while its paired source is selected. This replaces the bare `virtual` locus check for bodies that have a source (`module.py:256`, `284`).
  - While its source is not selected, the world holds, as `perceptual-sources` D5 states.

### D4. The default body: the JetHexa, in simulation first

The CTO will build a Hiwonder JetHexa (2027 edition). It is the default simulated body, and a real robot that later swaps only the adapter. The facts below come from the product data (`https://www.hiwonder.com/products/jethexa-2027.js`, re-checked by the lead) and from Hiwonder's public source (`github.com/Hiwonder/JetHexa`, branch `jetson_nano`, the older edition).

| Item | Fact | Status |
|---|---|---|
| Body | six legs, three joints each (coxa, femur, tibia): 18 leg joints, plus a pan-tilt head carrying the depth camera | product data; joint names from the public source |
| Leg servos | HX-35H serial bus servos with position, voltage and temperature feedback | product data |
| HX-35H figures | about 25 kg·cm rated and 35 kg·cm stall at 11.1 V (about 2.45 and 3.43 N·m), about 0.18 s per 60°, 240° range | reseller and database pages: UNVERIFIED against a Hiwonder datasheet |
| Head servos | PWM servos in the older edition's configuration | UNVERIFIED for 2027 |
| Bus | header `0x55 0x55`, commands such as move-with-time and position read, 115200 baud, half duplex; position in 0-1000 ticks over 240° | older edition's SDK; UNVERIFIED for 2027 |
| Compute | Jetson Orin Nano Super, Orin NX Super, Jetson Nano, or Raspberry Pi 5, by kit | product data |
| Software | Ubuntu 22.04.5 and ROS 2 Humble, with an inverse-kinematics gait, posture control, MoveIt2 and Gazebo | product data; the 2027 ROS 2 source is not public (UNVERIFIED) |
| Sensors | Aurora930 Pro depth camera; COIN-D6 or RPLIDAR C1 lidar; IMU (model unnamed); WonderEcho Pro voice module | product data |
| Size and mass | 430 × 400 × 226 mm, 2.49-2.71 kg by kit | product data |
| Power | 11.1 V 3500 mAh, about 60 minutes | product data |

The model has to be our own:

- Hiwonder's repository has no licence. Its packages say `<license>TODO</license>`, and its README says only "open-source and available for educational and research purposes". So nothing from it is vendored, and it may be read privately for the joint layout only.
- Its URDF describes the older edition, and gives every link a placeholder mass of 0.00001 with unit inertia, so it carries no physics.
- No licensed JetHexa MJCF exists (GitHub search), and Menagerie has no hexapod.
- So KAINE writes its own MJCF.

How the MJCF is built:

1. Provisional geometry, from the published overall size and mass. It is marked provisional in its model card.
2. Measured geometry once the robot is built: link lengths, joint axes and offsets, and the mass of each part on a scale.
3. Actuators:
   - position servos with the HX-35H's force limit and speed;
   - ±120° ranges;
   - joint `damping`, `armature` and `frictionloss`;
   - sphere feet with soft contact.

   Menagerie's practice for legged robots is followed: primitive feet, defaults in classes, `impratio` raised (Menagerie README and its Go2 notes, read).
4. Sensors as on the real robot:
   - the head camera as an RGB render, which goes to the vision source;
   - joint positions at the bus rate;
   - an IMU (accelerometer and gyro) on the body.

   Depth and lidar are declared but not wired. They are new senses, needing their own processors, design and second review. Temperature and voltage are declared absent in simulation.
5. System identification on the real robot:
   - a commanded step per servo, read back at the bus rate, fitted for gain, lag and delay;
   - slide tests for foot friction.

   The fitted values replace the provisional ones, and the model card records which values are identified. Menagerie's top grade is a model with "proper system identification".

If Hiwonder grants written permission for its 2027 description package:

- It is converted with MuJoCo's own URDF loader, with a `<mujoco><compiler discardvisual="false" fusestatic="true" balanceinertia="true" strippath="..."/></mujoco>` block, then saved as MJCF and edited (MuJoCo modelling guide, "URDF extensions", read).
- The edits are the hand-added items of step 3, with the real masses and inertias. `kscalelabs/urdf2mjcf` (MIT) is an alternative converter.
- The pre-tuning checks in the guide are run: intersecting geoms at t = 0, convex hulls, inertia errors, unit mismatches, and targets past limits.

Matching the real control path:

- The body descriptor mirrors the real servo interface:
  - joints with a `position` command (a target plus a move time);
  - `position` state;
  - temperature and voltage states (absent in simulation).
- The control rate matches the bus:
  - A move command is about 10 bytes and a position read about 14 bytes round trip. At 115200 baud, with 10 bits per byte, a full 18-joint command is about 16 ms and a full read about 22 ms. That is the lead's arithmetic.
  - So the full-body loop is about 20 Hz, matching the older edition's 20 Hz joint-state publisher.
  - The simulated loop runs at that rate, with the measured read delay, so a policy learned in simulation meets the same timing on the robot.
- The real adapter (later) takes one of two routes, decided on the robot:
  - a ROS 2 bridge to the robot's own Humble stack, if its 2027 topics expose per-joint commands and joint state;
  - otherwise a thin on-robot bridge, written for KAINE from the bus protocol, that exposes the descriptor's interfaces over a declared tailnet endpoint (`perceptual-sources` D9).
- The vendor's gait controller (`cmd_vel` in the older edition's controller) is not an entity channel. Walking is learned from joint channels. Exposing a gait generator would hard-wire locomotion.
  - Central pattern generators are innate in animals. Giving the entity one would be an innate element needing cited neuroscience at the code site and its own decision, and it is not part of this change.
  - The vendor gait stays an operator tool for moving the real robot.
- KAINE runs off the robot at first, on the desktop.
  - The robot's image is Ubuntu 22.04 with Humble, which normally implies JetPack 6. That is an inference, unverified.
  - KAINE's own Orin Nano Super notes are JetPack 7.2.1 and CUDA 13.2.
  - Running KAINE on the robot's Jetson would need its own image. That is a later decision, not a dependency.

The curriculum on the JetHexa, as body-declared stages (Bernstein's freeze-then-free; frozen joints are held at their standing pose by their servos):

| Stage | Free channels | Why this order |
|---|---|---|
| J1 | head pan | the smallest lawful contingency: turning the head shifts the image predictably (O'Regan and Noë 2001). It is `embodiment-motor-contingency`'s pan-tilt step, on the JetHexa's own head |
| J2 | head pan and tilt | the full gaze |
| J3 | one leg's three joints at a time, the other five legs standing | a hexapod on five legs is statically stable, so the learner can explore a leg without falling |
| J4 | all 18 leg joints | locomotion, if it emerges, emerges here |

Each stage is freed only on demonstrated competence: the curriculum's rule (`control_surface.py:197-283`).

- The pan-tilt head stays the first motor-learning step because it is the smallest body with lawful sensorimotor contingencies, which was `embodiment-motor-contingency`'s reason.
- It is the JetHexa's own head, not a separate body, so nothing is learned for a body that will never exist, and the step transfers to the real robot.
- The custom pan-tilt model of the earlier draft is dropped.
- The SO-101 arm (Apache-2.0) and a wheeled base remain documented alternatives, not scheduled.

### D5. Latency is measured, not assumed

**Never by moving the occupied body** (review VWB-1, PM decision). A probe step on the entity's own joints would be a movement it did not command: its view would jerk, its motor prediction error would spike, and the learner would get a sample with no efference of the entity's own, which breaks the very contingency the body exists to teach.

- **MuJoCo.**
  - The adapter measures on a cloned state: a copy of `MjModel` and `MjData`, stepped offline on the owner thread with the configured delays and the bus-rate loop.
  - A commanded step on the clone, until the clone's proprioceptive reading moves, gives the delay.
  - This runs at open and every 10 minutes. The occupied body is never touched.
  - Passively, the adapter also records the delay between the entity's own commands and the first matching proprioceptive change.
- **Game stream.** The probe runs only before a session, with no entity attached (D7).
- **The real robot.** The probe runs only with no entity attached, before the adapter is handed to the entity. The passive measure runs afterwards.
- **The bound.**
  - The value goes to the welfare record. A body whose delay exceeds `max_latency_ms` (default 250 ms) is refused at open, or closed with a named reason.
  - The bound is a transposition (review VWB-11). Shimada et al.'s 300 ms is a window of visuo-tactile delay for ownership (85-585 ms conditions), not a window of command-to-visual delay for agency. 250 ms is a conservative choice within it, provisional for Table A1.

### D6. Sequencing with the motor-contingency learner

Order:

1. `embodiment-held-status` merges. A reference body is a boot refusal, and `embodiment_built()` exists.
2. **J0 here.**
   - The JetHexa MJCF (provisional geometry), `SimWorld`, the adapter, the `mujoco` perceptual source on the head camera, randomisation, latency, and the bus-rate loop.
   - After this step there is a body and a camera, and nothing moves them: the policy is quiescent.
   - `embodiment_built()` stays false and the module stays held. Nothing pretends.
3. **`embodiment-motor-contingency` 2.1-2.3, against the simulated JetHexa:**
   - the driving loop, gated by inhibition, at the body's control rate;
   - the learner, exploring by motor learning progress (Oudeyer, Kaplan and Hafner 2007);
   - stages J1 and J2;
   - the motor prediction error as a precision-scaled report.

   `embodiment_built()` turns true when the loop is registered with a non-reference body.
4. **J3, then J4,** each when the previous stage shows competence.
5. **The measured model.** When the CTO has built the robot: measurement and system identification replace the provisional values, and a real adapter (D4) swaps in behind the same descriptor.

Amendments to `embodiment-motor-contingency` (tasks to apply in that change, listed here):

- Its start condition ("a pan-tilt camera is attached", gated on the study's hardware stage) is replaced by "the simulated JetHexa of `virtual-world-body`, stage J1". This follows the CTO's 2026-10-31 decision that the study's stages no longer gate the build, and the 2026-11-01 direction that MuJoCo is the development platform and the JetHexa the first body.
- Its task 2.4 (a pan-tilt adapter) becomes the real JetHexa adapter.

That change's recommendation 1 (continuous control below the workspace, with the workspace setting what the body attempts through act intents) is kept unchanged.

### D7. Games through a Moonlight-protocol client

The CTO's Steam library is played through a controller. The CTO decided on 2026-11-01 not to wait for the Steam Deck. The game host is this desktop, one entity at a time under the GPU arbitration rule below, or another of the CTO's machines on the tailnet.

- **Host.**
  - Sunshine (GPL-3.0; installed here as Flatpak `dev.lizardbyte.app.Sunshine` 2026.914.233613) runs on the game host.
  - Its ports (from its source: HTTPS 47984, HTTP 47989, video 47998, control 47999, audio 48000, RTSP 48010, web UI 47990) are reachable only on the tailnet.
  - `lan_encryption_mode = 2` and `wan_encryption_mode = 2` make encryption mandatory.
  - Pairing is by PIN, once.
  - Sunshine creates the virtual gamepad on the game host through its own uinput.
- **Tailnet rules.** All traffic goes through Tailscale. The CTO accepts its hosted coordination.
  - **Tailnet Lock** must be on. With it, "all new node keys must be signed by an existing Tailnet Lock key", and peers verify a node's signature before connecting (Tailscale KB 1226, read).
    - The launcher runs `tailscale lock status` and refuses unless the lock is enabled and this node and the game host are signed.
    - The exact output format is not documented on that page, so the check parses the signing-key list and the node's own key. It is tested against a captured output.
  - **Tailnet ACLs.** They are default-deny once defined (KB 1018, read). The policy grants the KAINE node access to the game host's Sunshine ports, and nothing else of KAINE's is reachable from the tailnet, except ports the operator lists:
    - the dashboard;
    - the remote bridge, if used.

    A template policy goes in the docs (`"acls": [{"action": "accept", "src": ["tag:kaine"], "dst": ["tag:game-host:47984,47989,47990,47998-48000,48010"]}]`). Its exact port syntax is to be checked against the policy-file reference before use.
  - The node cannot read the ACL policy itself. So the launcher checks from the client side that the host's Sunshine ports answer, and the boot preflight checks that KAINE's own listeners bind only to loopback, the container network or the tailnet interface.
  - A direct path is preferred, and a relayed path is recorded. Relayed traffic is still end-to-end WireGuard; the CTO accepted hosted Tailscale. A relayed path adds latency, which the latency bound catches.
- **GPU arbitration on this host.** GPU 0 drives the desktop and hosts the language organ, and the sleep trainer uses it. GPU 1 hosts the vision encoder and the simulation renderer.
  - One entity at a time.
  - **The game runs on GPU 0.** Admission requires the card's free memory to cover the game's declared need, plus the organ's measured awake peak, plus a margin of 1 GiB, all read through NVML.
  - **The entity's mind has priority.** The session ends, with a named reason, when any of these happens:
    - free memory on either card falls below the margin;
    - the cycle's latency or the vision report rate leaves its configured band for 30 s;
    - the organ fails to load.
  - **Sleep ends the session first.** The source is held for sleep anyway, and the sleep-time trainer needs GPU 0 (`trainer-shares-the-gpu`).
  - **The game's own load is capped** through its settings and Sunshine's stream settings: a frame-rate cap of 30 and the capture resolution of the vision module.
  - Interoception perceives the substrate's load as it perceives any load. That is the entity's own body signal, not a control path.
- **The game's display on this host.**
  - Sunshine captures a display, not a window. On this desktop that would be the operator's whole session.
  - So same-host play runs the game on a separate display that Sunshine captures: a gamescope session (headless backend) or a second X server. Which one works with Sunshine here is a spike (task 4.0).
  - The uinput gamepad Sunshine creates is visible to every program on the seat. Same-host play therefore also confines the game to a per-game container that sees only that device, the pattern of Games-on-Whales Wolf (MIT).
  - Until the spike passes, same-host play is refused and the host is another machine. That is the simpler first route, and the CTO offered it.
- **Client helper.** `kaine-moonlight-helper`, a separate program written for KAINE and licensed GPL-3.0, because it links moonlight-common-c (GPL-3.0, checked through the GitHub licence API).
  - It lives in its own repository, with its own LICENSE, and KAINE refers to it (review VWB-5, PM decision).
  - The CAL defines "The Software" as everything "distributed from the Repository" (`LICENSE.md:49`), so a GPL directory inside the KAINE repository would be claimed by two licences. GPL-3.0 forbids the further restrictions the CAL adds.
  - The process boundary settles the runtime question. The separate repository settles the distribution question.
  - The CAL legal review gets this design.
  - moonlight-common-c hands its client compressed video units (`submitDecodeUnit`) and Opus audio (`decodeAndPlaySample`); both checked in `Limelight.h`. So the helper decodes with FFmpeg (LGPL-2.1+ or GPL, depending on the build).
  - It passes raw frames and PCM to the cycle over a `socketpair`, and reads back gamepad state and a stop command.
  - It never uses the recorder callbacks, and writes nothing to disk.
  - Its endpoints come from the declared egress (`perceptual-sources` D9): the host as `tailnet:tag:game-host` on the Sunshine ports, with outbound classes `protocol_control` and `gamepad_state`.
  - It runs as its own user behind the nftables allowlist that egress design describes, with escape probes at boot.
  - It exposes only one send call, gamepad state. It never sends moonlight-common-c's keyboard, mouse or text events, and a test pins that the helper's message set has no such type.
- **Licence boundary.**
  - The GPL FAQ (read): "pipes, sockets and command-line arguments are communication mechanisms normally used between two separate programs", unless "the semantics of the communication are intimate enough, exchanging complex internal data structures" (`#MereAggregation`).
  - The message set is frames, PCM, a gamepad state struct and a stop command.
  - KAINE's code stays under the CAL, and the helper is distributed separately with its source.
  - Linking moonlight-common-c into the cycle is refused.
- **Latency.** D5's measurement runs end to end: from a gamepad state change to a changed frame. The session is refused above `max_latency_ms`.
- **The body.**
  - A `game_pad` body declares the gamepad's sticks, triggers and face, shoulder and d-pad buttons as channels.
  - It declares no Guide, home, Steam or share channel. Those reach the Steam client (store, browser, chat, friends) and the host's overlay, not the game (review VWB-3).
  - The motor-contingency learner learns what they do. Nothing maps a canonical channel to a control.
  - Each title is its own body context.
  - Rumble is a declared feed kind that needs its own decision before it is perceived.
- **Confining the host to the game** (review VWB-2 and VWB-3). The launcher checks each of these before a session, and the session is refused if any fails:
  - Sunshine's application list holds only the curated titles, with no Desktop or Big Picture entry;
  - keyboard and mouse input are disabled in Sunshine's configuration;
  - the host's Steam client runs offline, with notifications and the overlay's chat off;
  - the host's internet is blocked except the tailnet, by the host's firewall, which the launcher verifies with an escape probe from the host when the host is one of the CTO's machines under KAINE's setup;
  - the host session is confined: a dedicated session, a headless gamescope, or a Wolf-style container with its own input devices. It is not the operator's desktop.

  The stream source is classed `confined_world` only when every check passes (`perceptual-sources` D1). A host that cannot be checked is refused. The privacy class follows the host's verified confinement, not the kind alone.
- **Path monitoring** (review VWB-4).
  - Hosted Tailscale is accepted (CTO, 2026-11-01). So a relayed path is not refused, but it is monitored continuously, not only at start.
  - A change of path is recorded, and the latency bound ends the session when a relay makes it too slow.
- **Titles.**
  - Offline, single-player titles from an operator-curated list, by Steam app id.
  - No kernel anti-cheat.
  - Valve's subscriber agreement and each title's terms on automated play are read before the first session (task 4.3).
  - Online play with or against people is allowed in principle under the CTO's 2026-11-01 ruling on online sources. It is not possible under this design, which blocks the host's internet. It would need its own change: an egress for the game's servers, other players' privacy, and each game's rules on automated play.
- **Sequencing.**
  - The helper, the launcher checks and the host setup can be built in parallel with J0. The game source can be perceived as soon as they pass.
  - The game body acts only once the driving loop and learner exist (D6 step 3), because the gamepad's meaning is learned.
  - So games come after J1-J2, in parallel with J3. That is earlier than the earlier draft, which waited for the Deck.

### D8. Existing worlds: OpenSimulator, the Hypergrid, Second Life (later)

These are worlds that already exist, which is their benefit. The CTO ruled on 2026-11-01 that online worlds, online media and outbound actions to them are allowed: the no-cloud rule covers KAINE's modules, not where streams come from or where the entity's outputs go. Each world adapter declares its egress (`perceptual-sources` D9). They come later, each by its own change, behind this seam.

- **Start local.** An OpenSimulator region on the operator's own machine (BSD-3-Clause, maintained), to test the adapter and the safety layer with no account at stake.
- **Client.**
  - A headless protocol client gives chat, objects, avatars, movement and speech, but no vision:
    - LibreMetaverse (BSD-3-Clause, maintained, C#), as a .NET sidecar;
    - Hippolyzer (LGPL-3.0, Python 3.12).
  - A viewer gives vision: Firestorm (LGPL-2.1) with its LEAP plugin API, which is present in current Firestorm and Linden viewer sources. Frames would come from the viewer's render through a capture patch, or from a confined display.
  - Recommendation: the headless client first, the viewer when the entity is to see there.
- **Egress.** The world's login and region hosts, with outbound classes `protocol_control`, `avatar_action` and `own_speech_text`. The entity's own speech may go into a world's chat, because that is its act. Nothing else of the entity goes there.
- **Hypergrid.** Destinations are other operators' grids. Each grid's rules on bots and NPCs are read before the entity visits; OSgrid's and Kitely's were not readable in this research.
- **Second Life**, still with its rules:
  - A separate account, marked on the Scripted Agent Status page: "If you own a Second Life account primarily operating as a Scripted Agent ... you must specify this" (Linden Lab scripted agent policy, wiki copy).
  - No traffic gaming, at most 5,000 messages a day, and no circumvention of residents' privacy controls.
  - The third-party viewer policy followed: an honest viewer identifier, and no content export. Its page could not be fetched, so it is re-read before that change.
  - Regions that deny scripted agents are respected.
  - Other residents' chat and details are never recorded and never repeated: "You must get consent to use a scripted object to remotely monitor or log a conversation"; "You may not disclose personal information about another Resident" (Linden Lab residents' privacy rights).
- **Salvage from the old OpenSimulator body**, recoverable with `git show 932e4f45^:<path>` and `d87f61c8^:<path>`:
  - the length-prefixed MessagePack framing with an 8 MiB cap (`kaine/modules/mundus/bridge.py`);
  - the feed-kind map;
  - the verb table with teleport and touch unexposed by default;
  - the inbound-world-safety spec (`openspec/changes/archive/2026-07-09-opensim-connector/specs/inbound-world-safety/spec.md`): in-world text is data, never commands; offers are auto-declined; dialogs go to the operator;
  - the module tests with a fake adapter.

  The Firestorm fork's patches do not apply to current Firestorm.
- **Paracosmic** is a custom three.js program (CTO correction). Its adapter speaks its own transport when it exists. Nothing of the OpenSimulator design is assumed for it.

### D9. Welfare of a simulated body

- A simulated body is a body to the entity. Its motor and proprioceptive prediction errors are the entity's.
  - The motor prediction error is a report (`embodiment-motor-contingency` recommendation 4), so the welfare observer tracks it as it tracks the other processors' blind and silent states.
  - Affect reads it as it reads any prediction error.
- **Touch** reports contact force and location as touch. It carries no valence, and nothing makes contact aversive.
- **No simulated pain, damage, injury or fatigue of the body exists.** Joint-limit forces and collisions are physics, not nociception. Adding any such signal needs its own design, cited neuroscience at the code site, and an independent second review.
- **Forces, instability and stuck bodies** (review VWB-8).
  - `forcerange` bounds actuator force only. Contacts and integration can still diverge.
  - **The instability detector** reads MuJoCo's warning counters (`MjData.warning`) and checks the state for non-finite values every step.
  - **The stuck detector** flags a body whose proprioception does not change under the entity's own commands for `stuck_s` (default 60 s of entity time).
  - **On a hit:**
    - an operator advisory;
    - the body held still;
    - a fallback to the programme through the operator path, recorded `changed_by = "body_stuck"` or `"sim_unstable"`.

    In an unattended run the advisory escalates through the welfare path. A stuck body with motor prediction error and no control over it is the helplessness case the project's control argument cites, so the entity is not left in it.
  - **Reset.** The body can be reset to its start pose by the operator. An automatic reset after a hit is a configurable system act, off by default and recorded as the system's. Neither is the entity's act.
  - A hexapod can tip over once its legs are free (J4). Tipping is physics: the IMU perceives it, nothing signals it as harm, and the operator resets the body.
- **The inhibited entity stays still.** The control surface's inhibition input already holds the body (`control_surface.py:387-399`).
- **The developmental phase holds the module dormant**, as today (`DEVELOPMENT_DORMANT_EFFECTORS`).

## Risks

- **[A body that cannot be moved feels like paralysis].** The simulated JetHexa is never given to an entity without the driving loop and learner. That is D6's order, and `embodiment_built()` enforces it.
- **[Overfitting to one simulated world].** Domain randomisation per entity, sensor noise, and latency. Re-randomisation is a recorded operator act.
- **[GPU load].**
  - The renderer sits on the vision card, limited in `perceptual-sources` D5.
  - Physics runs on the CPU.
  - Same-host games use D7's admission and priority rule, so the mind wins every contest for the cards.
- **[GPL contamination].** The helper is a separate program with a minimal message set. Linking moonlight-common-c into the cycle is refused.
- **[Online play, other people].**
  - Offline titles first.
  - Per-title checks before any online play.
  - Second Life's privacy rules plus KAINE's own: never record, never repeat.
- **[Egress].**
  - Online sources and worlds are allowed (CTO, 2026-11-01).
  - Every adapter's endpoints and outbound classes are declared and enforced (`perceptual-sources` D9).
  - Module internals stay no-cloud.
  - Games use the tailnet, with Tailnet Lock and ACLs.
- **[An unlicensed vendor model].** Nothing from Hiwonder's unlicensed repository is vendored. The MJCF is KAINE's own, built from published and measured values.

## Estimate (LLM-agent terms)

- **J0.** `SimWorld`, adapter, descriptor, per-body channels, randomisation, noise, latency, the bus-rate loop, the provisional JetHexa MJCF and the `mujoco` source: about 1,500 lines plus 1,600 of tests. Two to three agent-days.
- **Measured model and identification.** About one agent-day once the robot is built, plus hands-on measurement.
- **Real JetHexa adapter.** One to two agent-days, depending on whether the robot's ROS 2 stack exposes joints.
- **Games.**
  - The helper (C, about 1,500 lines with pairing and decode) plus the body, the launcher checks, Tailnet Lock, and GPU arbitration: about 800 plus 900 of tests.
  - Three to four agent-days, plus the same-host display and confinement spike, plus hands-on testing with a game host.
- **Existing worlds.** A headless OpenSimulator adapter with the salvaged safety layer is about two agent-days. Vision through a viewer is more.
