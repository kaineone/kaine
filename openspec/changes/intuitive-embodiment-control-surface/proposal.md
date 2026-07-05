# An intuitive, learnable embodiment control surface for Mundus

> **Dependency re-pointed (2026-07-05):** `opensim-connector` is superseded by
> `body-agnostic-embodiment-adapters`, which turns Mundus into a body-agnostic
> control plane. This change now depends on that seam plus whichever adapter is
> live — not on `opensim-connector` directly. The continuous surface designed here
> is provided as an adapter *capability*: the canonical continuous channels
> (`drive, yaw_rate, gaze_yaw, gaze_pitch, interact`) are already reserved in the
> control-plane descriptor, so this change wires a producer to them rather than
> re-defining them. References to `opensim-connector` below read as "the live
> adapter" (OpenSim today, VR/paracosm later).

## Why

`opensim-connector` designed Mundus's avatar control as a **symbolic verb menu** —
`intent.avatar.{move, turn, say, sit_on, stand, animate, gesture, teleport, touch}`,
with locomotion as goal-based autopilot ("walk to this point"), not per-tick control.
And the producer was never built: nothing in the current build emits any
`intent.avatar.*` event, so every motor family is unreachable at runtime (see
`kaine/modules/mundus/module.py`). So there is a hole to fill — *and a choice about
what to fill it with.*

For a mind that has just been **born** out of the gestational curriculum
(`developmental-maturation-gate`), a symbolic verb menu is the wrong body. If the
viewer pre-solves "walk to X", "sit on Y", "touch Z", there is nothing sensorimotor
left for the entity to learn — it becomes a symbol-pusher issuing commands, not an
embodied agent discovering how its actions change what it perceives. The
developmental-embodiment literature is consistent that a body is learned from **few
continuous degrees of freedom, tightly coupled to sensory feedback, explored by the
agent itself** — and that skilled control is the progressive mastery of a redundant
body, with beginners *freezing* most degrees of freedom and *freeing* them as
competence grows (Bernstein 1967; O'Regan & Noë 2001; Rolf, Steil & Gienger 2010;
von Hofsten 1991).

This change fills the hole with the **learnable** surface: a small, continuous,
feedback-coupled action space the entity operates directly, a motor curriculum that
frees degrees of freedom as it masters them, and the fork work to expose continuous
control (rather than only the stock high-level verbs). The symbolic verbs are
demoted to operator-only tools, not the entity's surface. This is the embodied
counterpart to the womb's sensory curriculum and completes the arc: gestate → be
born → **learn to move**.

## What Changes (design-only scope)

**This is a DESIGN-ONLY change.** It ships no behaviour code — only the OpenSpec
artifacts (this proposal, `design.md`, `tasks.md`, and the
`embodiment-control-surface` spec delta). Snippets in `design.md` are illustrative.
Implementation is a later, separately-approved change and MUST NOT boot an entity.

The designed capability is a **minimal, continuous, learnable embodiment control
surface** for Mundus:

- **A minimal continuous action space** the entity operates directly — a small set
  of continuous scalars plus a single interaction trigger:
  `drive` (forward/back), `yaw_rate` (turn), `gaze_yaw` / `gaze_pitch` (look,
  decoupled from the body), and one `interact` trigger (touch/grab the gaze-fixated
  or nearest-in-front object). `strafe` is deferred. Every locomotion/gaze axis is
  **continuous and graded** so the entity can *babble* and explore; the single
  interaction primitive is deliberately not a `sit`/`touch`/`grab` menu.
- **The symbolic verb menu is NOT the entity's surface.** The stock high-level LEAP
  verbs (`teleport`, `sit_on`, `startAutoPilot` walk-to, `animate`, `gesture`) are
  left unexposed to the entity's learned policy (available to the operator only via
  their own logged-in viewer session — no new Mundus "operator console" is implied).
  They pre-solve exactly the sensorimotor mappings the entity is meant to learn, so the
  entity's learned policy does not issue them; at most they are internal primitives its
  policy
  could later compose, never its starting vocabulary.
- **The missing producer, built as continuous control.** The `intent.avatar.*`
  producer that `opensim-connector` left unbuilt is provided here as a **continuous
  control producer** — the entity's learned motor policy emitting the action scalars
  per tick (an Eidolon/Volition motor seam), forwarded by Mundus to the viewer. This
  supersedes the per-verb symbolic producer for the entity's own control.
- **The loop is closed — feedback is mandatory, not optional.** On every control
  tick the entity receives, time-aligned with its outgoing action: an **efference
  copy** of the scalars it emitted, **proprioceptive feedback** (resulting avatar
  velocity, heading, gaze direction, a contact/collision signal, and interact
  success/failure), and **visual feedback** (the rendered view). Without the
  efference copy and coupled feedback the same scalars are an open-loop joystick and
  nothing is learnable. The forward-model machinery KAINE already has (Soma's
  `SubstrateForwardModel`; the Phantasia world model) is reused to predict → compare
  → correct.
- **A motor curriculum: freeze then free.** The action space starts minimal at birth
  ({`drive`, `yaw_rate`} only, gaze locked, no interaction) and progressively frees
  degrees of freedom (gaze, then interaction) as the entity **demonstrates control**
  — a competence-gated unfreezing, measured not scheduled, mirroring the gestational
  sensory curriculum and Bernstein's freeze-then-free.
- **The fork work: continuous control over LEAP.** Stock Firestorm LEAP exposes the
  high-level `LLAgent` verbs and, for raw locomotion, only synthetic `LLWindow`
  key/mouse injection. The clean path is a small custom `LLAgent`-wrapping
  `LLEventAPI` that accepts the continuous setpoints per tick and emits the coupled
  feedback pump; the crude stopgap is mapping the scalars onto held synthetic keys /
  `AGENT_CONTROL_*` flags. Either way this rides the fork `opensim-connector` already
  plans. **Verify the fork actually re-enabled LEAP launching** (stock Firestorm
  ships it disabled) before assuming any of this is reachable.
- **Safety reuses Mundus's existing gates.** The two-layer gate
  (`[mundus].enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1`), workspace-inhibition
  pause of `intent.avatar.*`, world-mutating-action opt-in, and the inbound-world
  "data not commands" policy are reused unchanged. The continuous scalars are clamped
  to valid ranges. Only after the `embodied` stage (Change B) is the surface active.

## Impact

- **Affected spec capability:** `embodiment-control-surface` (ADDED, new capability):
  the minimal continuous action space, the exclusion of symbolic verbs from the
  entity surface, the mandatory feedback loop, the freeze-then-free motor curriculum,
  and the safety-reuse requirements.
- **Refines (does not silently contradict) `opensim-connector`:** its
  `world-action-intents` action vocabulary is **reframed** — the symbolic
  `intent.avatar.{...}` verbs become operator-only, and the entity's control is the
  continuous surface defined here. When `opensim-connector` is implemented/updated,
  its `world-action-intents` spec should point at this surface for the entity's own
  control. This dependency is called out explicitly (design §2); this change does not
  edit that not-yet-live spec.
- **Touch points for the future implementer** (design names them; no code here):
  `kaine/modules/mundus/module.py` and `bridge.py` (continuous action forwarding +
  feedback pump), a new continuous motor producer (Eidolon/Volition seam),
  `tools/mundus-leap/` (continuous-control LEAP op + feedback), the Firestorm fork
  (`firestorm-fork-notes.md`: the continuous `LLAgent` LEAP op), the forward-model
  reuse (Soma `SubstrateForwardModel` / Phantasia), and the `[mundus]` config.
- **Explicitly NOT touched:** the gestational womb (Change A); the stage machine
  (Change B, which gates entry here); Mundus's two-layer gate, inhibition handling,
  and inbound-world safety (reused, not modified); the OpenSim grid, physics, and
  in-world media (the operator's domain — this change adds no world content).
- **Relationship to other changes:** entered only after `developmental-maturation-gate`
  flips the stage to `embodied`; depends on `opensim-connector`'s Mundus module,
  LEAP shim, and Firestorm fork landing (this change extends them with a continuous
  surface). It is the world the gestation arc graduates into.
