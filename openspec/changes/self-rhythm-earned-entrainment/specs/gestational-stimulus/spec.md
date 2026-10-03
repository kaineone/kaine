## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Entrainment is measured on the intrinsic rhythm against surrogate beats
The entrain-then-autonomy marker SHALL be computed from the self-rhythm's population rate filtered to the self-rhythm's own physiological band (never a narrow band centred on the maternal beat), with zero-phase filtering, Hilbert phase over a window of at least 300 s of unperturbed samples, and the window edges trimmed. It SHALL pass only when the phase-locking value to the maternal beat exceeds that of every one of at least 19 surrogate beats generated as other mothers' heartbeats, the rhythm self-sustains during drive withdrawal, and the rhythm's frequency during withdrawal has moved toward the beat by at least the configured frequency-pull floor. Time-shifted copies of the same beat SHALL NOT be used as surrogates.

#### Scenario: An evoked response does not pass
- **WHEN** the self-rhythm shows a response locked to the beat but its intrinsic frequency during withdrawal has not moved toward the beat
- **THEN** the marker does not pass

#### Scenario: A foreign mother does not pass
- **WHEN** the self-rhythm was exposed to one mother's beat and is scored against another mother's beat
- **THEN** the marker does not pass

### Requirement: The self-rhythm has a slow intrinsic rhythm in a physiological band
The self-rhythm oscillator SHALL produce, undriven, a rhythm in the fetal breathing band (0.5-1.0 Hz; about 30-70 breaths per minute, Natale et al. 1988) from excitatory recurrence and activity-dependent synaptic depression, with its period able to adapt slowly within a clamped physiological band. The mechanism SHALL be cited at the code site.

#### Scenario: Undriven rhythm lies in band
- **WHEN** the self-rhythm runs without maternal drive at resting own drive
- **THEN** its dominant frequency lies between 0.5 and 1.0 Hz

### Requirement: Entrainment must be earned and validated offline before a study
Before a study uses a self-rhythm or measurement version, an offline validation with the real classes SHALL show: the marker false throughout the first 6 h; passing under the usual drive in at least 80% of seeds within the gestation budget; never passing with no drive, a foreign mother, a jittered beat or adaptation disabled; a withdrawn frequency specific to the presented beat rate (57, 70 and 84 bpm); and no capture at higher drive scales or higher own drive with adaptation disabled. The validation report SHALL be stored with the change, and the self-rhythm version SHALL be recorded in each birth record.

#### Scenario: Controls never pass
- **WHEN** the validation runs the no-drive, foreign-mother, jittered-beat and no-adaptation controls
- **THEN** no readout passes the marker in any of them
