# thymos-affect-coupling Specification

## Purpose
TBD - created by archiving change thymos-affect-coupling. Update Purpose after archive.
## Requirements
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

### Requirement: Familiarity cache persistence
Thymos SHALL serialize the per-agent familiarity cache so that coupling strength
is not cold-reset after a fork restore.

#### Scenario: Cache survives a serialize/deserialize round-trip
- **WHEN** the familiarity cache holds a non-empty entry and Thymos is serialized
  then deserialized
- **THEN** the same familiarity values are present and coupling uses them on the
  next event

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

