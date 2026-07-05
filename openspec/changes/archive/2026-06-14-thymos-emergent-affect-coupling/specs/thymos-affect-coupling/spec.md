# thymos-affect-coupling (delta)

## ADDED Requirements

### Requirement: Appraisal-routed perceived emotion
A detected speaker emotion (`audition.emotion`) SHALL be folded into Thymos's
own Scherer appraisal as a perceptual input, weighted by `familiarity` from the
latest `empatheia.agent_model`, and SHALL NOT be written directly to the
dimensional (valence/arousal/dominance) state. The entity's own appraisal —
together with its goal significance, coping, and novelty — SHALL determine the
classified emotion and the resulting bounded state change. The contribution
weight SHALL be `compute_coupling(coupling_base, coupling_familiarity_gain,
familiarity, coupling_ceiling)` and SHALL be clamped so no appraisal dimension
leaves `[-1, 1]`. Resonance is thereby an output of appraisal, not an imposed
shift toward the speaker's state.

#### Scenario: Perceived emotion is appraised, not imposed
- **WHEN** an `audition.emotion` event reports a strongly positive-valence emotion while coupling is enabled
- **THEN** Thymos's appraised intrinsic_pleasantness rises and the entity's own appraisal→state path moves valence upward
- **AND** no code path moves the dimensional state toward a fixed VAD target for that emotion

#### Scenario: Higher familiarity appraises others' emotion as more significant
- **WHEN** the same detected emotion is appraised at familiarity 0.2 versus 0.9
- **THEN** the appraisal contribution (and resulting state change) at 0.9 is strictly larger than at 0.2

#### Scenario: Perceived-emotion influence decays
- **WHEN** an `audition.emotion` arrives and then no further emotion events arrive for `decay_s`
- **THEN** its contribution to appraisal decays to zero and the dimensional state returns toward baseline via the existing drift dynamics

## MODIFIED Requirements

### Requirement: Graceful degradation and opt-out
Thymos SHALL use `coupling_base` as the contribution weight when no familiarity
is known for the speaker, and SHALL add no perceived-emotion contribution to
appraisal when `[thymos.coupling].enabled` is false.

#### Scenario: No Empatheia model uses base weight
- **WHEN** an `audition.emotion` arrives with no prior `empatheia.agent_model`
- **THEN** the appraisal contribution uses `coupling_base`

#### Scenario: Disabled coupling does nothing
- **WHEN** coupling is disabled and an `audition.emotion` arrives
- **THEN** the appraisal scores are identical to the no-perceived-emotion case and the dimensional state is not changed by coupling

## REMOVED Requirements

### Requirement: Familiarity-modulated affect coupling
**Reason:** Replaced by *Appraisal-routed perceived emotion*. The old requirement
mandated a direct, appraisal-bypassing write that shifted the dimensional state
toward the detected speaker emotion's VAD target. Perceived emotion is now folded
into the entity's own Scherer appraisal instead, so resonance is an emergent
output of appraisal rather than an imposed mirror-shift.

### Requirement: Cumulative-drift safeguard
**Reason:** The rolling-window rate cap existed only to stop the *direct*
appraisal-bypassing VAD write from pinning the dimensional state at a boundary.
With perceived emotion routed through appraisal (a small, bounded, decaying
contribution followed by the existing drift/hysteresis), there is no direct
write to cap; the safeguard and `coupling_max_rate_per_s` are removed.
Boundedness is now guaranteed by the appraisal-weight clamp and the decay window
(see *Appraisal-routed perceived emotion*).
