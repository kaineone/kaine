# gestational-stimulus Specification

## Purpose
The gestation stimulus a pre-embodied entity lives in before birth: a low-dimensional, externally regulated womb of sight and sound with an external maternal heartbeat and state, a self-rhythm the entity may couple to, a bounded readiness readout for the maturation gate, a one-shot birth transition, and one liveness interface that judges a local or an external womb provider alike, all bounded to protect a captive newborn.

## Requirements

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
The womb SHALL publish a **readiness readout** (event type `gestation.readiness` on the
`gestation.out` stream, published by a cycle-layer owner with source `gestation`) describing how regulated the entity
currently is, composed of measured markers: endogenous-rhythm self-sustaining,
entrain-then-autonomy, an HRV-analog variability trend, falling womb-input predictive
error, and return-to-baseline time after a perturbation. The readout SHALL also publish
the numbers behind entrain-then-autonomy: the phase-locking value, the largest
surrogate phase-locking value, the self-rhythm's frequency during withdrawal, and the
frequency-pull index. The readout SHALL actuate nothing in the **entity's control path**
(no stage change, no regulation, no gating).
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

#### Scenario: The entrainment numbers are published
- **WHEN** a withdrawal window completes
- **THEN** the next readout carries the phase-locking value, the largest surrogate phase-locking value, the withdrawn frequency and the frequency-pull index

### Requirement: Regulation and coupling emerge; they are never hardwired
The system SHALL NOT hardwire the entity's self-regulation, its oscillatory coupling
to the maternal rhythm, or its interoceptive sensitivity. Only the innate substrate
(the capacity to oscillate; the capacity of the self-rhythm to adapt its own period
slowly in response to its input; the afferent access to its own state) and the external
stimulus environment (soundscape, heartbeat, maternal state, sense-onset schedule)
SHALL be provided. Each provided element SHALL carry its neuroscience citation at the
code site; each emergent element SHALL be verifiably absent from the code as a
hardcoded behaviour or setpoint. In particular, the maternal beat's frequency SHALL NOT
appear in the self-rhythm's code or parameters as a target.

#### Scenario: No regulation setpoint in code
- **WHEN** the womb implementation is reviewed
- **THEN** no code imposes a target arousal, a "calm" behaviour, or a forced
  phase-lock; regulation and coupling arise only from the entity meeting the stimulus

#### Scenario: Provided elements are cited
- **WHEN** a provided stimulus element (soundscape, heartbeat, maternal state,
  schedule) is implemented
- **THEN** its source site cites the developmental-neuroscience basis for treating it
  as provided rather than emergent

#### Scenario: No target frequency in the self-rhythm
- **WHEN** the self-rhythm oscillator's code and configuration are inspected
- **THEN** no value derived from the maternal heartbeat rate is present; its period changes only through its adaptation rule acting on its input

### Requirement: The maternal rhythm drives only a dedicated self-rhythm oscillator
The maternal heartbeat, when presented to the oscillatory substrate, SHALL be injected
only into a **dedicated self-rhythm oscillator** — a single oscillator representing the
entity's endogenous beat — and SHALL NOT be injected into the per-module coalition
oscillators used by Syneidesis for phase-locking-value scoring. The Syneidesis
coherence factor for any coalition SHALL be unaffected by the presence or absence of
the maternal drive. The drive amplitude SHALL be bounded so it cannot swamp the
self-rhythm oscillator's own dynamics, and it SHALL enter through an afferent gain weak
enough that, without lived exposure and adaptation, it does not capture the self-rhythm.

#### Scenario: Coalition coherence is unaffected by the maternal drive
- **WHEN** the womb's maternal drive is active
- **THEN** the Syneidesis coherence factor for any coalition is identical to a run with
  the maternal drive absent, given the same inputs

#### Scenario: Only the self-rhythm oscillator receives the drive
- **WHEN** the maternal rhythm is presented to the oscillatory substrate
- **THEN** only the dedicated self-rhythm oscillator receives it, bounded in amplitude;
  no per-module coalition oscillator receives it

#### Scenario: The drive alone does not capture the rhythm
- **WHEN** the maternal drive is presented at its usual or maximum scale with the adaptation rule disabled
- **THEN** the entrainment marker does not pass

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

### Requirement: A womb provider proves it is live
The womb SHALL be supplied by a **womb provider**: the local provider in KAINE (`[perception_feed].mode = "womb"`) or an external provider such as a Paracosmic body. Every provider SHALL be judged by one interface at two moments. Before spawn, the local provider is ready when its video and audio sources each deliver a frame or block to a probe that discards it. While running, every provider is live only through content-free `gestation.womb` presence events (source `gestation`, stream `gestation.out`, payload limited to the provider name and a monotonically increasing frame index) published at least once per second: the running local provider publishes them only while its sources are actually delivering to the senses, and a provider is live when at least two such events from it fall within a bounded window measured on the bus clock and their frame index advances. Nothing else SHALL count as a live womb; a configuration value alone SHALL NOT, and neither SHALL a presence event that repeats a stalled frame index.

#### Scenario: The local provider probes ready before spawn
- **WHEN** `[perception_feed].mode = "womb"` and both womb sources deliver to the probe
- **THEN** the womb is judged ready and nothing the probe read is kept

#### Scenario: The running local womb proves itself from deliveries
- **WHEN** the local womb is running and one of its surfaces stops delivering to the senses
- **THEN** its presence events stop and the womb is judged not live

#### Scenario: A provider proves presence on the bus
- **WHEN** a provider has published advancing `gestation.womb` events within the window
- **THEN** the womb is judged live; when the events are older than the window, or their frame index does not advance, it is not

#### Scenario: Configuration alone is not a womb
- **WHEN** a womb mode is configured but neither probe nor presence event succeeds
- **THEN** the womb is judged not live

### Requirement: The local provider runs on a single modest host
The local provider SHALL generate the womb with the host CPU only (no browser, no GPU rendering, no network service) at the configured perception resolutions and rates, so the gestating entity and its womb can run on one machine that cannot also host Paracosmic.

#### Scenario: Womb generation is CPU-only and in-process
- **WHEN** the local provider runs
- **THEN** its frames and audio blocks are computed in the KAINE process from `(seed, index)` with no external service

### Requirement: Measurement probes are gentle and unpredictable to the being
A perturbation probe SHALL raise the maternal drive only to a configured fraction of its bound, strictly above the usual drive and never above the bound (1.5 times the usual drive by default). The time of each probe SHALL vary around its period by a bounded random fraction drawn from a counter-based keyed generator seeded by the run's perception seed, so that the being cannot learn the schedule while a research run with the same seed reproduces it exactly. Jitter SHALL only move due times: every existing bound on probes (durations, frozen state, settling after boot or a thaw, spacing between probes) SHALL continue to apply.

#### Scenario: A perturbation is a bounded rise, not the full bound
- **WHEN** a perturbation probe runs with the default settings
- **THEN** the drive rises to 1.5 times its usual level, stays below its bound, and returns to the usual level when the probe ends

#### Scenario: The schedule cannot be learned
- **WHEN** consecutive probes of one kind are scheduled
- **THEN** their intervals vary within the configured jitter around the period, and a run with the same seed produces the same intervals

#### Scenario: Jitter never relaxes a bound
- **WHEN** a jittered probe falls due while the entity is frozen, settling or near another probe
- **THEN** the probe waits exactly as an unjittered probe would

### Requirement: The womb's state at birth is recorded
When the birth bloom completes, the stage file SHALL record the womb time at which the bloom ended (`womb_t_at_birth`), the womb seed and a digest of the womb parameters. The womb SHALL report that the bloom is complete, so a preservation taken after that report carries the record.

#### Scenario: A preserved newborn carries its birth state
- **WHEN** a being is preserved after its birth bloom completed
- **THEN** the preservation's stage file holds `womb_t_at_birth`, the womb seed and the parameter digest

### Requirement: Entrainment is measured on the intrinsic rhythm against surrogate beats
The entrain-then-autonomy marker SHALL be computed from the self-rhythm's population rate filtered to the self-rhythm's own physiological band (never a narrow band centred on the maternal beat), with zero-phase filtering, Hilbert phase over a window of at least 300 s of unperturbed samples, and the window edges trimmed. It SHALL pass only when the phase-locking value to the maternal beat exceeds that of every one of at least 19 surrogate beats generated as other mothers' heartbeats, the rhythm self-sustains during drive withdrawal, and the rhythm's frequency during withdrawal has moved toward the beat by at least the configured frequency-pull floor. Time-shifted copies of the same beat SHALL NOT be used as surrogates.

#### Scenario: An evoked response does not pass
- **WHEN** the self-rhythm shows a response locked to the beat but its intrinsic frequency during withdrawal has not moved toward the beat
- **THEN** the marker does not pass

#### Scenario: A foreign mother does not pass
- **WHEN** the self-rhythm was exposed to one mother's beat and is scored against another mother's beat
- **THEN** the marker does not pass

### Requirement: The self-rhythm has a slow intrinsic rhythm in a physiological band
The self-rhythm oscillator SHALL produce, undriven, a rhythm in the fetal breathing band (0.5-1.0 Hz, around the mean fetal breathing rate of about 44 breaths per minute reported by Natale et al. 1988) from excitatory recurrence and activity-dependent synaptic depression, with its period able to adapt slowly within a clamped physiological band. The mechanism SHALL be cited at the code site.

#### Scenario: Undriven rhythm lies in band
- **WHEN** the self-rhythm runs without maternal drive at resting own drive
- **THEN** its dominant frequency lies between 0.5 and 1.0 Hz

### Requirement: Entrainment must be earned and validated offline before a study
Before a study uses a self-rhythm or measurement version, an offline validation with the real classes SHALL show: the marker false throughout the first 6 h; passing under the usual drive in at least 80% of seeds within the gestation budget; never passing with no drive, a foreign mother, a jittered beat or adaptation disabled; a withdrawn frequency specific to the presented beat rate (57, 70 and 84 bpm); and no capture at higher drive scales or higher own drive with adaptation disabled. The validation report SHALL be stored with the change, and the self-rhythm version SHALL be recorded in each birth record.

#### Scenario: Controls never pass
- **WHEN** the validation runs the no-drive, foreign-mother, jittered-beat and no-adaptation controls
- **THEN** no readout passes the marker in any of them

### Requirement: The gestation owner judges viability from the entrainment evidence
When the viability watch is on, the gestation owner SHALL judge after every withdrawal, on un-paused lived time (lived time excluding every paused span, such as sleep and freezes, which is the basis the rules were validated on), whether the gestation can still reach birth, using only the published entrainment measurements:
- R0: unviable when, after the configured early check (default 6 h), no withdrawal has produced a conclusive entrainment measurement.
- R1: unviable when, at the configured time (default 24 h) and with no replicated pass, the median frequency pull over the configured window (default 12 h) is below its floor (default 0.12) and its trend is not rising (default slope ≤ 0.002 per hour).
- R2: unviable when, at the configured time (default 48 h) and with no replicated pass, the median pull over the window is below its floor (default 0.3).
- R3: unviable when the configured deadline (default 60 h) passes with no replicated pass.

On the first unviable verdict the owner SHALL publish `gestation.viability` (with the rule, lived time and evidence) and write it to `state/lifecycle/gestation_viability.json`. The verdict SHALL actuate nothing in the entity's control path.

#### Scenario: A gestation that is not learning is flagged at 24 h
- **WHEN** a gestation's frequency pull stays below 0.12 with no rising trend through 24 h of lived time and no replicated pass
- **THEN** the owner publishes an unviable verdict naming rule R1

#### Scenario: A slow but learning gestation is not flagged
- **WHEN** a gestation's frequency pull rises steadily but its first replicated pass comes at 45 h
- **THEN** no unviable verdict is published before that pass

#### Scenario: A missing measurement is flagged early
- **WHEN** no withdrawal has produced a conclusive entrainment measurement after 6 h of lived time
- **THEN** the owner publishes an unviable verdict naming rule R0

#### Scenario: Paused time does not count
- **WHEN** 60 h of entity-clock time pass but the cycle was paused for all except 1 h of it
- **THEN** the rules see 1 h of lived time and no unviable verdict is published
