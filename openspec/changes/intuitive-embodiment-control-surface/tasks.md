# Tasks — An intuitive, learnable embodiment control surface

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go, and
> **do not boot an entity**. Phases map to `design.md`. Depends on `opensim-connector`
> (Mundus module, LEAP shim, Firestorm fork, frame side-channel) and
> `developmental-maturation-gate` (the `embodied` stage gate).

## W0 — Guardrails (read before starting)
- [ ] 0.1 Confirm approval and that the operator has resolved `design.md` §10
      (continuous op vs stopgap, competence readout, motor-policy locus, `say`
      exposure).
- [ ] 0.2 Re-read `design.md` §3/§5/§9: continuous few-DOF surface, **mandatory**
      coupled feedback, and the policy **emerges** (only the structure is provided).
- [ ] 0.3 **Verify the Firestorm fork re-enabled LEAP launching** (stock Firestorm ships
      it disabled) on the actual build before assuming the LEAP surface is reachable.

## W1 — Continuous control LEAP op (Firestorm fork, `firestorm-fork-notes.md`)
- [ ] 1.1 Add a custom `LLAgent`-wrapping `LLEventAPI` that accepts continuous setpoints
      `{drive, yaw_rate, gaze_yaw, gaze_pitch, strafe, interact}` per tick, writing them
      into the agent control-flag / camera path.
- [ ] 1.2 Emit a feedback pump on the same cadence: efference copy + proprioception
      (velocity, heading, gaze dir, contact/collision, interact result). Use binary LLSD
      if latency requires.
- [ ] 1.3 (Stopgap fallback, if 1.1 deferred) map scalars onto held synthetic
      `LLWindow` keys / `AGENT_CONTROL_*` — documented as coarse, first-bring-up only.

## W2 — LEAP shim (`tools/mundus-leap/`)
- [ ] 2.1 Relay the continuous control frames from Mundus to the viewer op (W1) and the
      feedback frames back, over the existing length-prefixed-MessagePack bridge.

## W3 — Mundus continuous forwarding + feedback (`kaine/modules/mundus/module.py`, `bridge.py`)
- [ ] 3.1 Consume a continuous `intent.avatar.control` (the six scalars) and forward it
      to the shim; clamp scalars to range at the boundary.
- [ ] 3.2 Publish the feedback pump onto the bus (efference copy + proprioception +
      collision/interact result) time-aligned so the forward model can consume it;
      preserve zero-raw-persistence on frames.
- [ ] 3.3 Honor inhibition (zero the action) and the two-layer gate + `embodied` stage
      gate; the surface is inert otherwise.
- [ ] 3.4 Confirm the symbolic `intent.avatar.{teleport,sit_on,animate,gesture}` verbs
      are NOT wired into the entity's learned policy (operator access is their own
      viewer session — no new Mundus operator console); `say` may remain.
- [ ] 3.5 On the birth-transition event (from `developmental-maturation-gate`), make the
      embodied world the sense source and activate this surface (subject to the
      `embodied` stage + two-layer gate); before birth the surface is inert. This is the
      reciprocal half of B's birth-handoff contract.

## W4 — Continuous motor producer (Eidolon/Volition seam)
- [ ] 4.1 Add the entity's continuous motor policy seam emitting `intent.avatar.control`
      per tick from the entity's learned policy (design §10.3). This is the producer
      `opensim-connector` left unbuilt — as continuous control, not symbolic verbs.
- [ ] 4.2 Wire the coupled feedback (W3.2) into the forward-model reuse: Soma
      `SubstrateForwardModel` / Phantasia world model (predict → compare → correct). Do
      NOT add a new learner.

## W5 — Motor curriculum: freeze then free (provided training/safety scaffold, not innate)
- [ ] 5.1 Implement the DOF progression M1 {drive,yaw} → M2 +gaze → M3 +interact → M4
      +strafe, starting minimal at birth. Frame it in comments as a **provided
      safety/training scaffold**, not an innate Bernstein mechanism (design §3/§9).
- [ ] 5.2 Gate each unfreezing on a motor-competence readout (falling forward-model
      error on free axes / stable goal-reaching), measured not scheduled. Cite Bernstein
      freeze-then-free at the site.

## W6 — Safety reuse (verify, don't reinvent)
- [ ] 6.1 Verify two-layer gate + `embodied` stage gate make the surface inert when
      unmet.
- [ ] 6.2 Verify inhibition zeroes the action; verify inbound-world "data not commands"
      policy still applies; verify world-mutating/economy actions stay opt-in and off
      the continuous surface.

## W7 — Emergent-not-hardwired
- [ ] 7.1 Add a source comment at the surface stating only the action-space structure +
      freeze-then-free progression are provided (cite Bernstein 1967; O'Regan & Noë
      2001; Wolpert et al. 1995); the policy and coupling emerge.
- [ ] 7.2 Confirm no code scripts a gait or maps an intent to a pre-solved world effect.

## W8 — Config (`config/kaine.toml`)
- [ ] 8.1 Add any `[mundus]` keys for the continuous surface (e.g. enabling the
      continuous op vs stopgap, curriculum thresholds), shipped conservative/off.

## W9 — Tests
- [ ] 9.1 Surface shape: the entity emits clamped continuous `drive`/`yaw`/`gaze` +
      single `interact`; `strafe` absent initially; gaze moves the view without body
      motion.
- [ ] 9.2 Symbolic exclusion: the entity's policy path cannot emit
      `teleport`/`sit_on`/autopilot-walk-to/`animate`/`gesture`; operator path can.
- [ ] 9.3 Closed loop: every action tick yields a time-aligned efference copy +
      proprioception + visual feedback; a surface missing feedback fails the test.
- [ ] 9.4 Curriculum: birth starts at {drive,yaw}; a DOF frees only when the competence
      readout crosses threshold, never on elapsed time alone.
- [ ] 9.5 Safety: inert without the two-layer gate or `embodied` stage; inhibition zeroes
      the action; scalars clamped.
- [ ] 9.6 Emergent: assert no scripted gait / intent→effect mapping exists.

## W10 — Validation
- [ ] 10.1 `openspec validate intuitive-embodiment-control-surface --strict` passes.
- [ ] 10.2 Mundus + bridge + forward-model test suites green; `opensim-connector`'s
      gates, inhibition handling, and inbound-world safety are reused unmodified.
