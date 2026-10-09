## MODIFIED Requirements

### Requirement: Appraisal-routed perceived emotion
A detected speaker emotion (`audition.emotion`) SHALL be folded into Thymos's
own Scherer appraisal as a perceptual input, weighted by `familiarity` from the
latest `empatheia.agent_model`, and SHALL NOT be written directly to the
dimensional (valence/arousal/dominance) state. The entity's own appraisal, together with its goal significance, coping, and
novelty, SHALL determine the classified emotion, and its intrinsic-pleasantness
check SHALL set the valence target, so the bounded state change runs through
the appraisal. The contribution
weight SHALL be `compute_coupling(coupling_base, coupling_familiarity_gain,
familiarity, coupling_ceiling)` and SHALL be clamped so no appraisal dimension
leaves `[-1, 1]`. Resonance is thereby an output of appraisal, not an imposed
shift toward the speaker's state.

#### Scenario: Perceived emotion is appraised, not imposed
- **WHEN** an `audition.emotion` event reports a strongly positive-valence emotion while coupling is enabled
- **THEN** Thymos's appraised intrinsic_pleasantness rises and valence relaxes upward toward the target that check sets
- **AND** no code path moves the dimensional state toward a fixed VAD target for that emotion

#### Scenario: Higher familiarity appraises others' emotion as more significant
- **WHEN** the same detected emotion is appraised at familiarity 0.2 versus 0.9
- **THEN** the appraisal contribution (and resulting state change) at 0.9 is strictly larger than at 0.2

#### Scenario: Perceived-emotion influence decays
- **WHEN** an `audition.emotion` arrives and then no further emotion events arrive for `decay_s`
- **THEN** its contribution to appraisal decays to zero and valence relaxes back toward the target set without it
