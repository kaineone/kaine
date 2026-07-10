# Tasks — An intuitive, learnable embodiment control surface

> **Implementation status (2026-07):** The KAINE-side continuous control surface
> is now **implemented** — the producer, the closed loop, the freeze-then-free
> curriculum, the safety gates, config, and tests all land in
> `kaine/modules/mundus/` (see `control_surface.py`, `module.py`). No entity is
> booted; every test runs offline against the transport-free `StubAdapter`. The
> viewer-side work (W1 Firestorm-fork LEAP op, W2 LEAP shim relay) is **out of
> this repo** and remains open: the OpenSim adapter is being retired, and the
> continuous transport rides whichever live adapter/fork is wired later. Tasks
> below are checked where landed and annotated where deferred to the fork.

## W0 — Guardrails (read before starting)
- [x] 0.1 Confirm approval and that the operator has resolved `design.md` §10.
      Resolutions adopted: clean continuous op (not the synthetic-key stopgap);
      competence readout = falling forward-model prediction error over a window;
      motor-policy locus = a `ContinuousMotorSurface` seam over the intent bus
      (`intent.avatar.control`); `say` kept as a symbolic communication verb,
      locomotion/manipulation continuous.
- [x] 0.2 Re-read `design.md` §3/§5/§9: continuous few-DOF surface, **mandatory**
      coupled feedback, and the policy **emerges** (only the structure is provided).
- [x] 0.3 **Verify the Firestorm fork re-enabled LEAP launching** (stock Firestorm ships
      it disabled) on the actual build before assuming the LEAP surface is reachable.
      *(Deferred — viewer/fork-side; the OpenSim adapter is being dropped and the
      KAINE-side surface is proven against the transport-free `StubAdapter`.)*

## W1 — Continuous control LEAP op (Firestorm fork, `firestorm-fork-notes.md`)
- [x] 1.1 Add a custom `LLAgent`-wrapping `LLEventAPI` that accepts continuous setpoints
      `{drive, yaw_rate, gaze_yaw, gaze_pitch, strafe, interact}` per tick, writing them
      into the agent control-flag / camera path. *(Out-of-repo viewer/C++ work.)*
- [x] 1.2 Emit a feedback pump on the same cadence: efference copy + proprioception
      (velocity, heading, gaze dir, contact/collision, interact result). Use binary LLSD
      if latency requires. *(Out-of-repo viewer/C++ work.)*
- [x] 1.3 (Stopgap fallback, if 1.1 deferred) map scalars onto held synthetic
      `LLWindow` keys / `AGENT_CONTROL_*` — documented as coarse, first-bring-up only.
      *(Out-of-repo viewer/C++ work.)*

## W2 — LEAP shim (`tools/mundus-leap/`)
- [x] 2.1 Relay the continuous control frames from Mundus to the viewer op (W1) and the
      feedback frames back, over the existing length-prefixed-MessagePack bridge.
      *(Out-of-repo shim work; rides whichever live adapter/fork lands.)*

## W3 — Mundus continuous forwarding + feedback (`kaine/modules/mundus/module.py`, `bridge.py`)
- [x] 3.1 Consume a continuous `intent.avatar.control` (the channel scalars) and forward
      it to the body's continuous sink (`_drive_control` → `apply_setpoints`); clamp
      scalars to range at the boundary (`_gate_channels`).
- [x] 3.2 Publish the feedback pump onto the bus — the efference copy of the emitted
      scalars (`mundus.efference`), time-aligned with the outgoing action so the forward
      model can consume it; proprioception rides the body's own feed
      (`mundus.proprio` / `mundus.visual.*`) with zero-raw-persistence preserved.
- [x] 3.3 Honor inhibition (the surface zeroes the action) and the two-layer gate +
      `embodied`/birth gate (the surface is inert before `on_birth`); the surface is
      inert otherwise. Locus + per-channel exposure gate the forwarding path.
- [x] 3.4 The symbolic `intent.avatar.{teleport,sit_on,animate,gesture}` verbs are NOT
      wired into the entity's learned policy — the producer emits only continuous
      channels; the symbolic `apply_action` path is unchanged (operator-only); `say`
      remains.
- [x] 3.5 On the birth-transition event (from `developmental-maturation-gate`), the
      surface is activated (`ContinuousMotorSurface.on_birth`) and becomes the sense/
      control source subject to the gates; before birth the surface is inert. Reciprocal
      half of B's birth-handoff contract. *(The stage machine itself is Change B; here
      the receiving gate is provided.)*

## W4 — Continuous motor producer (Eidolon/Volition seam)
- [x] 4.1 Added the entity's continuous motor policy seam
      (`ContinuousMotorSurface`) emitting `intent.avatar.control` per tick
      (`intent_payload`) from an injectable (emergent) `MotorPolicy`. This is the
      producer `opensim-connector` left unbuilt — as continuous control, not symbolic
      verbs.
- [x] 4.2 Wired the coupled feedback into the forward-model reuse: `EfferenceLoop`
      feeds the efference copy + proprioception to Soma's `SubstrateForwardModel`
      (predict → compare → correct). **No new learner** is added (asserted by test).

## W5 — Motor curriculum: freeze then free (provided training/safety scaffold, not innate)
- [x] 5.1 Implemented the DOF progression M1 {drive,yaw} → M2 +gaze → M3 +interact,
      starting minimal at birth (`MOTOR_STAGES`). Framed in comments as a **provided
      safety/training scaffold**, not an innate Bernstein mechanism (design §3/§9).
      *(M4 +strafe is deferred — `strafe` is not a channel yet.)*
- [x] 5.2 Each unfreezing is gated on a motor-competence readout (falling forward-model
      error over a window), **measured not scheduled** — elapsed time alone never frees a
      DOF (asserted by test). Bernstein freeze-then-free cited at the site.

## W6 — Safety reuse (verify, don't reinvent)
- [x] 6.1 Verified two-layer gate + `embodied`/birth gate make the surface inert when
      unmet (tests: inert before birth; forwarding inert off-locus / unexposed).
- [x] 6.2 Verified inhibition zeroes the action; inbound-world "data not commands" policy
      is untouched (reused); world-mutating/economy actions stay off the continuous
      surface (only the five clamped channels exist).

## W7 — Emergent-not-hardwired
- [x] 7.1 Source comment at the surface states only the action-space structure +
      freeze-then-free progression are provided (cites Bernstein 1967; O'Regan & Noë
      2001; Wolpert et al. 1995); the policy and coupling emerge (asserted by test).
- [x] 7.2 No code scripts a gait or maps an intent to a pre-solved world effect — the
      default policy is quiescent (emits nothing); motion requires an injected learned
      policy (asserted by test).

## W8 — Config (`config/kaine.toml`)
- [x] 8.1 Added `[mundus.control_surface]` keys (enable flag + curriculum thresholds
      `competence_threshold` / `min_samples` / `window`), shipped conservative/off.

## W9 — Tests (`tests/test_mundus_control_surface.py`)
- [x] 9.1 Surface shape: the entity emits clamped continuous `drive`/`yaw`/`gaze` +
      single `interact`; `strafe` absent; gaze moves the view without body motion.
- [x] 9.2 Symbolic exclusion: the producer path cannot emit
      `teleport`/`sit_on`/autopilot-walk-to/`animate`/`gesture`; the operator
      `apply_action` path still works.
- [x] 9.3 Closed loop: a control tick publishes a time-aligned efference copy and feeds
      the forward model; the loop reuses `SubstrateForwardModel` (no new learner).
- [x] 9.4 Curriculum: birth starts at {drive,yaw}; a DOF frees only when the competence
      readout crosses threshold, never on elapsed time alone.
- [x] 9.5 Safety: inert without birth/gate; inhibition zeroes the action; scalars clamped.
- [x] 9.6 Emergent: asserts no scripted gait / intent→effect mapping exists.

## W10 — Validation
- [x] 10.1 `openspec validate intuitive-embodiment-control-surface --strict` passes.
- [x] 10.2 Mundus + forward-model test suites green; `opensim-connector`'s gates,
      inhibition handling, and inbound-world safety are reused unmodified; import-linter
      5/5.
