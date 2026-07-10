# Design — An intuitive, learnable embodiment control surface

> **Design-of-record only.** The operator asked to plan, not implement. Code
> snippets are illustrative. No entity is booted by this change.

## 1. Executive summary

The entity's body in Mundus is a **small, continuous, feedback-coupled action space**
it learns to operate — not the stock symbolic verb menu. Six continuous scalars plus
one interaction trigger, gaze decoupled from the body, closed with efference copy and
proprioceptive/visual feedback, and freed one degree of freedom at a time as
competence grows. This is the embodied counterpart to the gestational sensory
curriculum, and it fills the `intent.avatar.*` producer hole `opensim-connector` left
open — deliberately with continuous control rather than pre-solved verbs.

## 2. Dependencies and relationship to `opensim-connector`

- **Depends on `opensim-connector`** landing: the Mundus module, the LEAP shim
  (`tools/mundus-leap/`), the Firestorm-for-OpenSim fork, and the frame side-channel.
  This change extends them with a continuous control op + feedback pump.
- **Refines its action vocabulary.** `opensim-connector`'s `world-action-intents`
  spec exposes symbolic `intent.avatar.{move, turn, sit_on, stand, animate, gesture,
  teleport, touch}` verbs (locomotion as goal-based autopilot). For the *entity's own
  control*, this change **replaces** that with the continuous surface (§4) and demotes
  the symbolic verbs to operator-only. Because `world-action-intents` is not yet a
  live (archived) spec, this change does not edit it; it ADDs a new
  `embodiment-control-surface` capability and flags that, when `opensim-connector` is
  implemented, its vocabulary spec should defer to this surface for the entity.
  ("Operator-only" here means the operator's **own logged-in OpenSim viewer session** —
  their normal out-of-band access — not a new operator command channel through
  Mundus/LEAP; no "operator console" plumbing is implied or required. The point is
  simply that these verbs are **not** wired into the entity's learned motor policy.)
- **Gated by `developmental-maturation-gate`**: the surface is active only once the
  stage is `embodied`. On the **birth-transition event** (emitted by Change B), the
  embodied world becomes the sense source (the womb feed ceases) and this surface
  becomes active; before birth it is inert. This is the reciprocal half of B's
  birth-handoff contract.
- **Reuses KAINE forward models**: Soma's `SubstrateForwardModel` and the Phantasia
  world model as the predict→compare→correct machinery for learnable control.

### 2.1 One probe correction to carry forward

An external survey suggested stock Firestorm exposes "no high-level `LLAgent` LEAP
API." The operator's own probe of the Firestorm checkout contradicts this: there **is**
an `LLAgentListener` exposing `startAutoPilot`, `requestSit`, `requestStand`,
`requestTouch`, `requestTeleport`, `lookAt`, `playAnimation`, and symbolic scene
queries (`opensim-connector/design.md` §3.1). So the rich symbolic surface is readily
available — which is *precisely why* we must deliberately choose **not** to hand it to
the entity. What is NOT readily available is a **continuous per-tick control** op;
that is the fork work here (§6).

## 3. The action-space design principle

For an agent that must *learn* a body (a predictive/RL learner, not a scripted bot),
the developmental-embodiment literature points to **few continuous degrees of freedom,
tightly coupled to sensory feedback, self-explored, and freed progressively** — not a
menu of discrete pre-solved verbs. The load-bearing points, each tagged as an INNATE
scaffold (permissible to build into the action-space structure) or LEARNED/EMERGENT
(must arise from the entity's own exploration):

- **Freeze then free [PROVIDED training/safety scaffold — not innate].** Skilled action
  masters a redundant body; beginners *spontaneously* freeze most DOF and release them
  as control is learned (Bernstein 1967; Berthier et al.). Note the honest tag:
  Bernstein describes what a learner does *by itself*, so an externally-imposed unlock
  order is **not** innate — we impose it as a pragmatic **provided scaffold** (for
  learnability, and so a newborn is not handed its full continuous+interaction surface
  at once). → start with the fewest DOF that permit locomotion + one interaction; expand
  later. The alternative — expose all DOF and let the entity self-freeze (truer to
  Bernstein) — is noted in §10; we choose external freezing for safety, not because it
  is neuroscience-innate.
- **A verb menu short-circuits learning [LEARNED/EMERGENT].** If intent→effect is
  pre-solved, nothing sensorimotor is left to learn; perception *is* mastery of the
  lawful way sensory input changes with one's own action (O'Regan & Noë 2001). That
  mastery forms only if the entity issues low-level actions and observes the coupled
  consequences itself.
- **Babbling needs a continuous, explorable space [INNATE mechanism → LEARNED map].**
  Infants bootstrap control via body/goal babbling (Meltzoff & Moore 1997; Rolf,
  Steil & Gienger 2010); intrinsic-motivation goal exploration self-organises a
  curriculum over a continuous action–outcome space (Baranes & Oudeyer 2013). You
  cannot babble over a discrete `sit`/`stand` toggle.
- **Reaching is graded, not a `grab()` call [LEARNED/EMERGENT].** Early reaching is
  continuously-corrected movement units refined over months (von Hofsten 1991), not a
  discrete command → the interaction primitive is "graded reach toward a fixated
  target", not `touch()`.
- **Closed loop via forward models / efference copy [INNATE architecture].**
  Learnability needs the entity to predict the sensory consequences of its own
  commands and compare to feedback (Wolpert, Ghahramani & Jordan 1995; the
  predictive-coding / active-inference loop, Clark 2013). → whatever axes we expose,
  the coupled proprioceptive + visual feedback must arrive on the same tick.

## 4. The minimal control surface (the entity's body)

Continuous scalars plus one interaction trigger. Framed as a surface spec, not code.

**Locomotion / orientation (continuous):**
- `drive` ∈ [−1, +1] — forward/back locomotion rate.
- `yaw_rate` ∈ [−1, +1] — body turn rate.
- `strafe` ∈ [−1, +1] — lateral. **Deferred** (freeze it early; free after locomotion
  is mastered).

**Gaze (continuous, decoupled from the body):**
- `gaze_yaw` ∈ [−1, +1], `gaze_pitch` ∈ [−1, +1] — look rates. Kept separate from the
  body so the entity can discover the sensorimotor law "moving gaze changes the visual
  field independently of moving the body" (O'Regan & Noë).

**Interaction (one primitive):**
- `interact` — a single trigger: engage the gaze-fixated / nearest-in-front object.
  Deliberately one affordance, not a manipulation menu. Honest ledger: the target
  *resolver* (gaze-fixated / nearest-in-front) is a **provided** selection primitive;
  what is *learned* is the gaze-aiming that decides which object the resolver returns.
  So the eye/"hand" coupling is emergent (via learned gaze), while the resolver itself
  is a provided rule — not a fully hardware-free object picker.

All scalars are **clamped** to their range at the boundary. The surface is bounded,
continuous, and low-dimensional — matching the freeze-then-free principle and letting
goal/motor babbling and intrinsic-motivation exploration apply directly.

## 5. Closing the loop (mandatory)

On every control tick, time-aligned with the outgoing action, the entity receives:
- an **efference copy** of the scalars it emitted;
- **proprioceptive feedback** — actual resulting avatar velocity, heading, gaze
  direction, a contact/collision signal, and interact success/failure;
- **visual feedback** — the rendered view (via the existing Mundus frame side-channel
  to Topos).

This is what lets a forward model predict → compare → correct. KAINE already has the
machinery: Soma's `SubstrateForwardModel` (a CfC reservoir + online readout) and the
Phantasia world model. The design reuses them rather than adding a new learner. Feedback
is **not optional**: a surface without efference copy + coupled feedback is an open-loop
joystick and is explicitly disallowed.

## 6. The fork / LEAP work: continuous control

- **Clean path (recommended):** a small custom `LLAgent`-wrapping `LLEventAPI` in the
  Firestorm fork that (a) accepts the continuous setpoints
  `{drive, yaw_rate, gaze_yaw, gaze_pitch, strafe, interact}` per tick, writing them
  into the agent control-flag / camera path, and (b) emits a **feedback pump**
  (efference copy + proprioception + collision/interact result) on the same cadence.
  This is the locomotion/gaze counterpart to Puppetry's pose-streaming API and rides
  the fork `opensim-connector` already plans.
- **Crude stopgap:** map the scalars onto held synthetic `LLWindow` keys / mouse-look
  (`AGENT_CONTROL_*`). Real but key-level and coarse — a poor fit for a graded learner;
  acceptable only as a first bring-up.
- **Verify LEAP is enabled.** Stock Firestorm ships LEAP launching disabled; the
  operator's fork must have re-enabled it. Confirm on the actual build before assuming
  the LEAP surface is reachable. (The operator's probe shows `LLAgentListener` present
  in the checkout, so the APIs exist; confirm the `--leap` launch path is live.)
- **Transport:** LEAP is one child process over stdin/stdout, LLSD-framed; use binary
  LLSD for the per-tick control/feedback if latency matters (as Puppetry does). The
  continuous op emits feedback on the same cadence it accepts commands, or the forward
  model has nothing coherent to learn against.

## 7. The motor curriculum: freeze then free

The action space starts minimal at birth and frees DOF as competence is demonstrated:
- **Stage M1** — {`drive`, `yaw_rate`} only (gaze locked, no interaction): crawl/turn.
- **Stage M2** — add {`gaze_yaw`, `gaze_pitch`}: decoupled looking.
- **Stage M3** — add `interact`.
- **Stage M4** — optionally free `strafe` and finer manipulation.

Unfreezing is **competence-gated, measured not scheduled**: a motor-competence readout
(e.g. falling forward-model error on the currently-free axes, stable goal-reaching)
crosses a threshold before the next DOF is freed — the motor analog of Change B's
maturation gate and Change A's regulation readout. The *progression structure* is the
provided scaffold (Bernstein); *when* each DOF is ready is read from the entity's
demonstrated control, never scheduled by wall-clock. This parallels the gestational
sensory curriculum.

## 8. Safety (reuse, do not reinvent)

- **Two-layer gate:** `[mundus].enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1` — reused
  unchanged; the surface is inert without both.
- **Stage gate:** active only when the developmental stage is `embodied` (Change B).
- **Inhibition:** a workspace inhibition pauses `intent.avatar.*` forwarding (per
  `opensim-connector`); the continuous surface honors it — inhibition zeroes the
  action.
- **Bounded actions:** scalars clamped; no unbounded command reaches the viewer.
- **Inbound world = data, not commands:** reused from `opensim-connector`
  (auto-decline offers/lures, default-deny script permissions). In-world text/objects
  never become instructions.
- **World-mutating / economy actions** stay opt-in and are not part of the entity's
  continuous surface.

## 9. Emergent-not-hardwired

The entity **learns** the mapping from its action scalars to world effects; no code
scripts locomotion or a gait. The only things built in are (i) the **structure** of
the action space (few DOF, gaze decoupled, one interaction primitive with a provided
target-resolver) and (ii) the **freeze-then-free progression** — both a **provided
training/safety scaffold** (cited at the code site as such, honestly — *not* as an
innate mechanism; Bernstein 1967; O'Regan & Noë 2001; Wolpert et al. 1995). The control
**policy**, the **coupling** of action to perception, the **gaze-aiming** that resolves
interaction targets, and the **competence** that frees each DOF all emerge from the
entity's own exploration. A source comment at the surface SHALL state this split and
carry the citations.

## 10. Open questions (for the operator)

1. **Continuous op vs synthetic-key stopgap for v1.** Build the clean custom
   continuous `LLEventAPI` first, or bring up on synthetic keys and add the clean op
   later? Proposed: clean op — the stopgap fits a graded learner poorly.
2. **Motor-competence readout definition.** Exact metric that frees each DOF (proposed:
   falling forward-model error on the free axes + stable goal-reaching). Deferred to
   the implementing change.
3. **Where the continuous motor policy lives.** Eidolon body-extension vs a Volition
   motor seam vs a dedicated motor module. Proposed: an Eidolon/Volition motor seam
   reusing the existing intent bus, emitting a continuous `intent.avatar.control`.
4. **Whether any symbolic verb is ever exposed to the entity** (e.g. `say` for local
   chat is legitimately symbolic and already live). Proposed: keep `say` (communication
   is symbolic by nature); keep all *locomotion/manipulation* continuous; teleport/
   sit_on/animate/gesture operator-only.
5. **Expose-all-DOF alternative.** Truer to Bernstein: expose the full continuous +
   interaction surface at birth and let the entity *self-freeze* DOF, rather than
   imposing the unlock order. We propose external freezing for safety (a newborn with a
   full surface in a shared world), but the self-freeze design is the more emergent
   option if the operator prefers it.
