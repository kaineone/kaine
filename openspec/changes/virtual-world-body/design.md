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

The channel names carry no meaning to the entity. `pan.position` is a label for the operator and the records. What a channel does is what the motor forward model learns. Nothing maps a drive or a goal to a joint.

### D3. The MuJoCo adapter

- **The world.**
  - One `SimWorld` (`kaine/sim/world.py`) holds `MjModel` and `MjData`, built from the body's MJCF and a room scene with a few movable objects.
  - It is shared in process with the `mujoco` perceptual source, which renders its camera.
- **Actuators.**
  - Position servos (`<position>` with `kp`, `kv`, `forcerange`, `ctrlrange`), with gains taken from a real servo. B2 uses the Menagerie SO-101's Feetech STS3215 parameters (kp 998.22, kv 2.731, forcerange ±2.94, timestep 0.005).
  - First-order actuator lag through `dyntype="filter"`, a native MuJoCo actuator dynamics type.
  - Actuator command `delay`, native for `general` actuators via `nsample` and `delay`.
  - The research pass read all of these in the XML reference, and the lead checked the dynamics and gain enums in the installed 3.16.0.
- **Sensors.**
  - MuJoCo applies sensor `delay` and `interval`.
  - It does not apply `noise`. It stores the value, and a static joint with `noise=0.5` read with standard deviation 0 in the installed version (research pass, checked by running it).
  - So the adapter adds Gaussian noise itself, at each sensor's declared standard deviation, from a run-seeded generator.
- **Rates.**
  - Physics `timestep` 0.002-0.005 s. A control decimation gives `control_rate_hz` between 50 and 200.
  - Matched to hobby servos: Dynamixel's USB latency timer defaults to 16 ms and is advised to be lowered to 1 ms (ROBOTIS e-manual).
  - Delays of 3-20 ms follow Tan et al.'s measured 3 ms servo and 15-19 ms controller latencies.
- **Domain randomisation.**
  - Per run seed: link masses, joint damping, friction, actuator gains, actuator and sensor delays, sensor noise, and material colours and textures of the scene. Ranges are those of Peng et al. and Tan et al., narrowed for a first body.
  - The sampled values go in the run manifest. They are parameters, not perception.
  - The entity lives in one sampled world per run, so its body is consistent within a run.
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

### D4. The bodies

| Stage | Body | Model and licence | Real counterpart (for later) |
|---|---|---|---|
| B1 | pan-tilt camera head: 2 hinge joints, 2 position servos, a camera on the tilt link | custom MJCF from Menagerie `dynamixel_2r` (MIT, Duclusaud and Passault) | two hobby servos on a bracket with a USB camera |
| B2 | 5-DoF arm with gripper and wrist camera | Menagerie `robotstudio_so101` (Apache-2.0), vendored with its LICENSE | the SO-101 open-hardware arm, with a LeRobot driver |
| B3 | B2 on a differential-drive base with `<velocity>` wheel actuators | custom MJCF, modelled on LeKiwi | a LeKiwi-style base |

- No Menagerie model is a pan-tilt head, so B1 is a short custom file.
- Stretch 3 (Apache-2.0) has head, arm and base in one model, but its real counterpart is a commercial robot. It is kept as an alternative.
- Tidybot's base uses position joints with kp = 1e6, which is not physical, so it is not used.
- Every model's licence is fetched and kept beside it. No Meta-owned model or asset is used.

### D5. Latency is measured, not assumed

- At open, and every 10 minutes, the adapter measures the command-to-feedback delay: a commanded joint step until the proprioceptive reading moves. This is the delay a learner experiences.
- The value goes to the welfare record.
- A body whose measured delay exceeds `max_latency_ms` (default 250 ms, inside the 300 ms window of Shimada et al.) is refused at open, or closed with a named reason.
- For MuJoCo this is the configured delays plus the loop. For a game stream it is the network and the decoder (D7).

### D6. Sequencing with the motor-contingency learner

Order:

1. `embodiment-held-status` merges. A reference body is a boot refusal, and `embodiment_built()` exists.
2. **B1 here.** `SimWorld`, the adapter, the pan-tilt MJCF, the `mujoco` perceptual source, randomisation and latency.
   - After this step there is a body and a camera, and nothing moves them: the policy is quiescent.
   - `embodiment_built()` stays false and the module stays held. Nothing pretends.
3. **`embodiment-motor-contingency` 2.1-2.3, against the simulated head:**
   - the driving loop, gated by inhibition, at the body's control rate;
   - the learner, exploring by motor learning progress (Oudeyer, Kaplan and Hafner 2007);
   - the body-declared stages: pan, then pan and tilt;
   - the motor prediction error as a precision-scaled report.

   `embodiment_built()` turns true when the loop is registered with a non-reference body.
4. **B2, then B3,** each joined when the previous body's curriculum shows competence, and each by its own PR.

Amendments to `embodiment-motor-contingency` (tasks to apply in that change, listed here):

- Its start condition ("a pan-tilt camera is attached", gated on the study's hardware stage) is replaced by "the simulated pan-tilt body of `virtual-world-body` B1". This follows the CTO's 2026-10-31 decision that pilots and the study's stages no longer gate the build, and the 2026-11-01 direction that MuJoCo is the development platform.
- Its task 2.4 (a pan-tilt adapter) becomes the real-hardware adapter that later swaps in behind the same descriptor.

That change's recommendation 1 (continuous control below the workspace, with the workspace setting what the body attempts through act intents) is kept unchanged.

### D7. Games through a Moonlight-protocol client (held)

The CTO's Steam library is played through a controller. One host cannot run a game and the entity together without contending for the GPUs, so games wait for the CTO's Steam Deck on the tailnet.

- **Host.**
  - Sunshine (GPL-3.0; installed here as Flatpak `dev.lizardbyte.app.Sunshine` 2026.914.233613) runs on the game host: the Deck, or this desktop.
  - Its ports (from its source: HTTPS 47984, HTTP 47989, video 47998, control 47999, audio 48000, RTSP 48010, web UI 47990) are bound or firewalled to the tailnet interface.
  - `lan_encryption_mode = 2` and `wan_encryption_mode = 2` make encryption mandatory.
  - Pairing is by PIN, once.
  - Sunshine creates the virtual gamepad on the game host through its own uinput. On the Deck that pad exists on the Deck's seat, not the operator's desktop.
- **Client helper.** `tools/kaine-moonlight-helper/`, a separate program written for KAINE and licensed GPL-3.0, because it links moonlight-common-c (GPL-3.0, checked through the GitHub licence API).
  - moonlight-common-c hands its client compressed video units (`submitDecodeUnit`) and Opus audio (`decodeAndPlaySample`); both checked in `Limelight.h`. So the helper decodes with FFmpeg, whose licence is LGPL-2.1+ or GPL depending on the build.
  - It passes raw frames and PCM to the cycle over a `socketpair` and reads back gamepad state (axes and buttons) and a stop command.
  - It never uses moonlight-common-c's recorder callbacks, and writes nothing to disk.
- **Licence boundary.**
  - The GPL FAQ (read): "pipes, sockets and command-line arguments are communication mechanisms normally used between two separate programs", unless "the semantics of the communication are intimate enough, exchanging complex internal data structures" (`#MereAggregation`).
  - The message set is frames, PCM, a gamepad state struct and a stop command: arm's length.
  - KAINE's code stays under the CAL, and the helper is distributed separately with its source.
  - Linking moonlight-common-c into the cycle is refused, because that would make one combined work.
  - Starfire (Apache-2.0, Rust, Windows and macOS only, unverified provenance) and a clean-room client from the MIT-licensed Wolf protocol documentation are noted as alternatives. Neither is recommended now.
- **Network.**
  - The tailnet only. Before each session the helper's launcher checks `tailscale status` for the host peer and refuses unless the path is `direct`.
  - A DERP relay is Tailscale-operated infrastructure, and a relayed session is a cloud hop, even though WireGuard keeps it end-to-end encrypted.
  - A self-hosted DERP with `OmitDefaultRegions`, or Headscale (BSD-3-Clause), is the operator's option for a fully self-run tailnet.
- **Latency.** D5's measurement runs end to end: gamepad state change to a changed frame. The session is refused above `max_latency_ms`.
- **The body.**
  - A `game_pad` body declares a virtual gamepad's two sticks (4 axes), 2 triggers and its buttons as channels.
  - The motor-contingency learner learns what they do in a given game, as it learns a joint. Nothing maps `drive` to the left stick.
  - Each title is its own body context: game control mappings differ, which is the interference case of D1's context argument.
  - Rumble returned from the game is a candidate touch-like feed. It is declared by the body and needs its own decision before it is perceived.
- **Titles.**
  - Offline, single-player titles from an operator-curated list, by Steam app id.
  - The entity must not play against or alongside people online: other players' privacy, the no-outbound rule, and the game's and platform's rules on automated play. Valve's subscriber agreement on automation is not yet checked, and is task 4.3.
  - A title using kernel anti-cheat is excluded.
- **Single-host alternative, not recommended now.**
  - Capture the game through PipeWire screencast, and give it a uinput gamepad confined to a per-game container that sees only that device, the pattern of Games-on-Whales Wolf (MIT).
  - A uinput pad on the operator's seat is visible to every program there, and the GPU contention remains.
- **Held.** Refused at boot until all of these hold:
  - the Deck is on the tailnet;
  - the direct-path, encryption and latency checks pass;
  - the helper and its dependencies are installed with the CTO's OK;
  - an independent second review has passed.

### D8. Existing worlds: OpenSimulator, the Hypergrid, Second Life (later)

These are worlds that already exist, which is their benefit. They come later, each by its own change, behind this seam.

- **Start local.** An OpenSimulator region on the operator's own machine (BSD-3-Clause, maintained): no terms-of-service exposure and no cloud.
- **Client.**
  - A headless protocol client gives chat, objects, avatars, movement and speech, but no vision:
    - LibreMetaverse (BSD-3-Clause, maintained, C#), as a .NET sidecar;
    - Hippolyzer (LGPL-3.0, Python 3.12).
  - A viewer gives vision: Firestorm (LGPL-2.1) with its LEAP plugin API, which is present in current Firestorm and Linden viewer sources. Frames would have to come from the viewer's own render through a capture patch, as the old fork had, or from a confined display.
  - Recommendation: the headless client first, the viewer when the entity is to see there.
- **Hypergrid.** Destinations are other operators' grids. Each is a cloud dependency and needs its operator's permission. The CTO decides per grid.
- **Second Life**, last:
  - A separate account, marked on the Scripted Agent Status page: "If you own a Second Life account primarily operating as a Scripted Agent ... you must specify this" (Linden Lab scripted agent policy, wiki copy).
  - No traffic gaming, at most 5,000 messages a day, and no circumvention of residents' privacy controls.
  - The third-party viewer policy followed: an honest viewer identifier, and no content export.
  - Regions that deny scripted agents are respected.
  - KAINE never records perception. Beyond that, the entity must not repeat residents' chat or personal details: "You must get consent to use a scripted object to remotely monitor or log a conversation" (Linden Lab residents' privacy rights).
  - The third-party viewer policy page itself could not be fetched, so it must be re-read before that change.
- **Salvage from the old OpenSimulator body**, recoverable with `git show 932e4f45^:<path>` and `d87f61c8^:<path>`:
  - the length-prefixed MessagePack framing with an 8 MiB cap (`kaine/modules/mundus/bridge.py`);
  - the feed-kind map (proprio, scene, entity, chat, frame, notice, action result);
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
- **Forces and stuck bodies.**
  - Forces are bounded by `forcerange`, so nothing the entity does can make the simulation unstable.
  - A body that is stuck (fallen, wedged) can be reset to its start pose by the operator. The reset is recorded and is the operator's act, not the entity's.
- **The inhibited entity stays still.** The control surface's inhibition input already holds the body (`control_surface.py:387-399`).
- **The developmental phase holds the module dormant**, as today (`DEVELOPMENT_DORMANT_EFFECTORS`).

## Risks

- **[A body that cannot be moved feels like paralysis].** B1 is never given to an entity without the driving loop and learner. That is D6's order, and `embodiment_built()` enforces it.
- **[Overfitting to one simulated world].** Domain randomisation per run, sensor noise, and latency.
- **[GPU load].** The renderer sits on the vision card, limited in `perceptual-sources` D5. Physics runs on the CPU. Games run on another host.
- **[GPL contamination].** The helper is a separate program with a minimal message set. Linking moonlight-common-c into the cycle is refused.
- **[Online play, other people].** The curated offline list. Second Life's privacy rules plus KAINE's own.
- **[Cloud].** Games use the tailnet with a direct path required. Existing worlds beyond a local region are a CTO decision per grid.

## Estimate (LLM-agent terms)

- **B1.** `SimWorld`, adapter, descriptor, per-body channels, randomisation, noise, latency, pan-tilt MJCF and the `mujoco` source: about 1,200 lines plus 1,400 of tests. Two agent-days.
- **B2 and B3.** About one agent-day each, after B1's learner works.
- **Games.** The helper (C, about 1,500 lines with pairing and decode) plus the body and launcher checks (about 600 plus 700 of tests). Three to four agent-days, plus hands-on testing with the Deck.
- **Existing worlds.** A headless OpenSimulator adapter with the salvaged safety layer is about two agent-days. Vision through a viewer is more.
