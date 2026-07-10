# embodiment-control-surface (spec delta — DESIGN ONLY)

## ADDED Requirements

### Requirement: The entity's embodiment control is a minimal continuous action space
The entity's own avatar control in Mundus SHALL be a minimal, continuous, low-
dimensional action space: continuous scalars for `drive` (forward/back), `yaw_rate`
(body turn), and `gaze_yaw` / `gaze_pitch` (look, decoupled from the body), plus a
single `interact` trigger that engages the gaze-fixated or nearest-in-front object.
`strafe` SHALL be deferred (not exposed initially). Every locomotion and gaze axis
SHALL be continuous and graded (so the entity can explore/babble over it), and each
SHALL be clamped to its valid range at the boundary. The interaction SHALL be one
primitive, NOT a menu of distinct manipulation verbs. Its target *resolution*
(gaze-fixated / nearest-in-front) is a **provided** selection primitive; only the
gaze-aiming that determines *what* gets resolved is learned — so the eye/"hand"
coupling is emergent, while the resolver itself is honestly a provided rule.

#### Scenario: The surface is continuous and low-dimensional
- **WHEN** the entity controls its avatar
- **THEN** it emits continuous `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch` scalars
  (clamped to range) and at most a single `interact` trigger, with `strafe` absent

#### Scenario: Gaze is decoupled from the body
- **WHEN** the entity changes `gaze_yaw` / `gaze_pitch` without changing `drive` /
  `yaw_rate`
- **THEN** the visual field shifts without the body moving, so gaze and locomotion are
  independently controllable

### Requirement: Symbolic high-level verbs are not the entity's control surface
The system SHALL NOT expose the stock high-level wire-shim verbs (`teleport`, `sit_on`,
`stand`, goal-based autopilot walk-to, `animate`, `gesture`) to the entity as its
learnable control surface. They SHALL be operator-only tools or left unexposed; the
entity's learned motor policy SHALL NOT issue them as its primary means of moving.
Communication verbs (e.g. local chat `say`) MAY remain exposed, since communication is
symbolic by nature; locomotion and manipulation SHALL be continuous.

#### Scenario: The entity does not move by symbolic verbs
- **WHEN** the entity intends to move or interact
- **THEN** it does so through the continuous action space, and no `teleport`,
  `sit_on`, autopilot-walk-to, `animate`, or `gesture` verb is part of its surface

#### Scenario: Symbolic verbs remain available to the operator
- **WHEN** the operator issues a symbolic verb
- **THEN** it is honored as an operator-only tool, distinct from the entity's control
  surface

### Requirement: The control loop is closed with mandatory coupled feedback
The system SHALL deliver, on every control tick and time-aligned with the entity's
outgoing action, an efference copy of the emitted scalars, proprioceptive feedback
(resulting avatar velocity, heading, gaze direction, a contact/collision signal, and
interact success/failure), and visual feedback (the rendered view). A control surface
WITHOUT efference copy and coupled feedback SHALL NOT be shipped — it is an open-loop
joystick and is disallowed. The existing forward-model machinery (Soma's substrate
forward model; the Phantasia world model) SHALL be reused for the predict-compare-
correct loop rather than adding a separate learner.

#### Scenario: Feedback arrives coupled to action
- **WHEN** the entity emits an action on a tick
- **THEN** it receives, on the same cadence, an efference copy, proprioceptive
  feedback, and visual feedback for that action

#### Scenario: An open-loop surface is rejected
- **WHEN** a control surface omits efference copy or coupled proprioceptive/visual
  feedback
- **THEN** it does not satisfy this requirement and is not shipped

### Requirement: The motor curriculum frees degrees of freedom by demonstrated competence
The action space SHALL start minimal at birth — `drive` and `yaw_rate` only, gaze
locked, no interaction — and SHALL free additional degrees of freedom (gaze, then
`interact`, then optionally `strafe`) only as the entity **demonstrates control** of
the currently-free axes, measured by a motor-competence readout (e.g. falling forward-
model error on the free axes; stable goal-reaching). Unfreezing SHALL be gated by
demonstrated competence, NOT by a wall-clock schedule. This externally-imposed unlock
order is a **provided training/safety scaffold** (for learnability and for not handing
a newborn its full continuous+interaction surface at once), NOT an innate mechanism —
Bernstein's freezing-then-freeing describes what a learner spontaneously does; here it
is imposed as a pragmatic scaffold and cited as such. When each DOF is ready SHALL be
read from the entity's control, never scheduled.

#### Scenario: Birth begins with the fewest degrees of freedom
- **WHEN** the entity is first embodied
- **THEN** only `drive` and `yaw_rate` are active; gaze is locked and `interact` is
  unavailable

#### Scenario: A degree of freedom frees on demonstrated competence
- **WHEN** the motor-competence readout on the currently-free axes crosses its
  threshold
- **THEN** the next degree of freedom (gaze, then interact) is freed; if competence is
  not demonstrated, no DOF is freed regardless of elapsed time

### Requirement: Embodiment control reuses Mundus's existing safety gates
The continuous control surface SHALL be inert unless the Mundus two-layer gate
(`[mundus].enabled` and `KAINE_MUNDUS_OPERATOR_APPROVED=1`) is satisfied AND the
developmental stage is `embodied`. A workspace inhibition SHALL pause the surface (the
action is zeroed while inhibited). Inbound in-world text and objects SHALL remain data,
not commands (reusing the inbound-world-safety policy). World-mutating and economy
actions SHALL stay opt-in and SHALL NOT be part of the entity's continuous surface.

#### Scenario: The surface is inert without the gates
- **WHEN** the two-layer gate is not satisfied or the stage is not `embodied`
- **THEN** the control surface forwards no action to the viewer

#### Scenario: Inhibition zeroes the action
- **WHEN** a workspace inhibition is active
- **THEN** the continuous action is zeroed and nothing is forwarded to the viewer

### Requirement: The control policy emerges; only the action-space structure is provided
The system SHALL NOT script locomotion, a gait, or an action-to-effect mapping. Only
the **structure** of the action space (few DOF, gaze decoupled from body, one
interaction primitive with a provided target-resolver) and the **freeze-then-free
progression** SHALL be built in — as a provided training/safety scaffold, cited at the
code site (and honestly, not as an innate mechanism). The control policy, the
action-perception coupling, and the competence that frees each DOF SHALL emerge from
the entity's own exploration.

#### Scenario: No scripted gait or mapping
- **WHEN** the embodiment surface is reviewed
- **THEN** no code maps an intent to a pre-solved world effect or scripts a gait; the
  entity learns the mapping through feedback-coupled exploration

#### Scenario: The provided scaffold is cited
- **WHEN** the action-space structure and freeze-then-free progression are implemented
- **THEN** a source comment cites the developmental-motor-learning basis (Bernstein
  1967; O'Regan & Noë 2001; Wolpert et al. 1995) for treating them as provided scaffold

### Requirement: The embodied surface receives the birth handoff and becomes the sense source
The embodied world SHALL, on the birth-transition event emitted by the
developmental-stage capability, become the entity's sense source (taking over from the
ceasing womb feed), and the control surface SHALL become active — subject to the safety
gates (the `embodied` stage and the Mundus two-layer gate). Before the birth handoff,
the embodied surface SHALL be inert.

#### Scenario: Birth hands the senses to the embodied world
- **WHEN** the birth-transition event fires and the safety gates are satisfied
- **THEN** the embodied world becomes the sense source and the control surface becomes
  active

#### Scenario: The embodied surface is inert before birth
- **WHEN** the entity has not yet been born (stage is still `gestation`)
- **THEN** the embodied surface is inert and is not the sense source
