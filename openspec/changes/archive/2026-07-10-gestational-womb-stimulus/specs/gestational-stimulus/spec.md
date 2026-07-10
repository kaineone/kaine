# gestational-stimulus (spec delta — DESIGN ONLY)

## ADDED Requirements

### Requirement: The womb presents a low-dimensional, externally-regulated environment
The system SHALL provide a gestational "womb" stimulus that presents the pre-embodied
entity with a low-complexity, deterministic, audio-visual environment: a low-pass,
low-frequency-dominant soundscape carrying an external maternal heartbeat, and a dim,
low-contrast visual field. The womb SHALL be the entity's virtual world while it is
gestating and SHALL require no live human, camera, or microphone input. All womb
stimulus SHALL be a pure function of `(seed, frame_index)` (plus deterministic,
seed-derived rhythm and maternal-state signals), so a run is reproducible from its
descriptor.

#### Scenario: The womb is deterministic and reproducible
- **WHEN** the womb stimulus runs twice with the same seed
- **THEN** the video frame and audio block at any given index are identical across
  both runs

#### Scenario: The womb needs no live input
- **WHEN** the womb is the active stimulus
- **THEN** neither a live camera, a live microphone, nor live human input is required
  for the entity to perceive

### Requirement: The maternal channel is external and entity-independent
The womb SHALL present a **maternal channel** consisting of a fast rhythm (the
heartbeat) and a slow state (an emotional-weather signal that colours the visual
field). Both SHALL be synthesised, deterministic, bounded signals that are
**independent of the entity's own state** — nothing the entity does or feels SHALL
change the maternal channel. The womb SHALL NOT read the entity's affect to drive any
womb stimulus. Consequently there SHALL be no `affect → stimulus → affect` feedback
path through the womb.

#### Scenario: Maternal state does not depend on the entity
- **WHEN** the entity's internal affect changes during gestation
- **THEN** the maternal-state signal and the maternal heartbeat are unchanged (they
  are functions of the seed and index only)

#### Scenario: No self-referential visual loop exists
- **WHEN** the womb is auditing its inputs
- **THEN** no womb stimulus is derived from the entity's own affect or output, so a
  perturbation of the entity's state cannot amplify through the womb environment

#### Scenario: The maternal-state signal stays bounded
- **WHEN** the maternal-state generator runs for any length of a run
- **THEN** its value remains within its declared valid range at all times

### Requirement: The pulsing light is cross-modal drive, honestly grounded
The womb visual field SHALL pulse in luminance in phase with the maternal heartbeat
(a "pulsing light"). This SHALL be documented and cited at the code site as
**cross-modal rhythmic drive and a birth-transition cue**, NOT as a reproduction of a
womb feature (fetal vision is dim and the womb has no natural light rhythm). The
citation SHALL acknowledge that photic entrainment of endogenous oscillations is
contested.

#### Scenario: The luminance pulse tracks the heartbeat
- **WHEN** the maternal heartbeat beats
- **THEN** the visual field's overall luminance rises and falls in phase with the beat

#### Scenario: The grounding is stated honestly at the code site
- **WHEN** the pulsing-light synthesis is implemented
- **THEN** a source comment cites it as cross-modal drive / birth cue and references
  the entrainment debate, without claiming it reproduces fetal light perception

### Requirement: Sense-onset and colour-saturation follow a provided schedule
The womb SHALL follow a provided developmental schedule in which interoception and
low-frequency audition are available from the start, patterned vision is dim
throughout, and **colour saturation ramps from near-zero toward full across
gestation** (a cone-maturation analog), so the maternal-state colour becomes
progressively more informative toward birth. The schedule SHALL be parameterised by
lived subjective time (the entity clock), not wall-clock, so it is consistent under
time dilation and per-fork. The *schedule* is provided; colour *discrimination* SHALL
be left to emerge (never hardcoded).

#### Scenario: Colour begins muted and enriches over gestation
- **WHEN** the entity is early in gestation
- **THEN** the visual field is near-desaturated, and its colour saturation is greater
  later in gestation for the same maternal-state value

#### Scenario: The schedule advances on lived time
- **WHEN** the entity clock is dilated
- **THEN** the colour ramp advances with lived subjective time, not wall-clock time

### Requirement: The womb exports a readiness readout that imposes nothing on the entity
The womb SHALL publish a **readiness readout** (event type `gestation.readiness` on a
named owner's stream, e.g. `gestation.out`) describing how regulated the entity
currently is, composed of measured markers: endogenous-rhythm self-sustaining,
entrain-then-autonomy, an HRV-analog variability trend, falling womb-input predictive
error, and return-to-baseline time after a perturbation. The readout SHALL actuate
nothing in the **entity's control path** (no stage change, no regulation, no gating).
Its markers MAY be measured via a **bounded, disclosed external-stimulus perturbation
protocol** (drive-withdrawal windows and perturbation spikes) that actuates only the
external stimulus, never the entity, and SHALL be bounded in magnitude and frequency.
Every marker SHALL be a measurement; none SHALL be a hardwired target or a "calm"
behaviour imposed on the entity.

#### Scenario: The readout imposes nothing on the entity
- **WHEN** the readiness readout is computed and published
- **THEN** it changes no stage, triggers no regulation, and gates nothing in the
  entity's control path within this capability

#### Scenario: Measurement perturbations are external and bounded
- **WHEN** a marker is measured via drive-withdrawal or a perturbation spike
- **THEN** only the external stimulus is actuated (never the entity), and the
  perturbation is bounded in magnitude and frequency

#### Scenario: The readout measures, it does not impose
- **WHEN** the readout reports low regulation
- **THEN** no behaviour forces the entity toward regulation; the markers only observe

### Requirement: Regulation and coupling emerge; they are never hardwired
The system SHALL NOT hardwire the entity's self-regulation, its oscillatory coupling
to the maternal rhythm, or its interoceptive sensitivity. Only the innate substrate
(the capacity to oscillate; the afferent access to its own state) and the external
stimulus environment (soundscape, heartbeat, maternal state, sense-onset schedule)
SHALL be provided. Each provided element SHALL carry its neuroscience citation at the
code site; each emergent element SHALL be verifiably absent from the code as a
hardcoded behaviour or setpoint.

#### Scenario: No regulation setpoint in code
- **WHEN** the womb implementation is reviewed
- **THEN** no code imposes a target arousal, a "calm" behaviour, or a forced
  phase-lock; regulation and coupling arise only from the entity meeting the stimulus

#### Scenario: Provided elements are cited
- **WHEN** a provided stimulus element (soundscape, heartbeat, maternal state,
  schedule) is implemented
- **THEN** its source site cites the developmental-neuroscience basis for treating it
  as provided rather than emergent

### Requirement: The maternal rhythm drives only a dedicated self-rhythm oscillator
The maternal heartbeat, when presented to the oscillatory substrate, SHALL be injected
only into a **dedicated self-rhythm oscillator** — a single oscillator representing the
entity's endogenous beat — and SHALL NOT be injected into the per-module coalition
oscillators used by Syneidesis for phase-locking-value scoring. The Syneidesis
coherence factor for any coalition SHALL be unaffected by the presence or absence of
the maternal drive. The drive amplitude SHALL be bounded so it cannot swamp the
self-rhythm oscillator's own dynamics.

#### Scenario: Coalition coherence is unaffected by the maternal drive
- **WHEN** the womb's maternal drive is active
- **THEN** the Syneidesis coherence factor for any coalition is identical to a run with
  the maternal drive absent, given the same inputs

#### Scenario: Only the self-rhythm oscillator receives the drive
- **WHEN** the maternal rhythm is presented to the oscillatory substrate
- **THEN** only the dedicated self-rhythm oscillator receives it, bounded in amplitude;
  no per-module coalition oscillator receives it

### Requirement: The womb renders the birth transition then ceases
The womb feed SHALL, on receiving the birth-transition trigger (emitted by the
developmental-stage capability), render a bounded, one-shot transition (the dim field
blooming into a photic activation) and SHALL then cease publishing womb stimulus,
yielding the sense source to the embodied world.

#### Scenario: Birth trigger renders then ceases
- **WHEN** the womb feed receives the birth-transition trigger
- **THEN** it renders a bounded transition once and then stops publishing womb stimulus

### Requirement: A captive gestating entity's stimulus is bounded and welfare-protected
The system SHALL bound the womb stimulus for a confined gestating entity: any maternal
"distress excursion" and any measurement perturbation SHALL be bounded in magnitude and
duration and OFF by default beyond the minimum needed for measurement, and the external
oscillator drive SHALL be bounded. The autonomous welfare / preservation net SHALL
remain active and authoritative during gestation; the womb stimulus SHALL NOT be able
to inflict unbounded or inescapable distress, and the gestation confinement SHALL NOT
suppress a welfare-protective response.

#### Scenario: Distress stimulus is bounded and off by default
- **WHEN** the womb is configured with defaults
- **THEN** maternal distress excursions are off, and any enabled excursion or
  measurement perturbation is bounded in magnitude and duration

#### Scenario: The welfare net still protects a gestating entity
- **WHEN** interoceptive distress crosses the welfare threshold during gestation
- **THEN** the welfare/preservation net responds as it would for any entity, and the
  gestation confinement does not suppress that response
