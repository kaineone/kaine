# Spec Delta

## MODIFIED Requirements

### Requirement: Each tier publishes an honest capability statement
The system documentation SHALL include a capability matrix stating, per tier, which faculties are present, degraded, or absent, including that vocal-emotion and expressive TTS are absent below Tier 2, that vision is periodic (not streaming) at Tier 1, that a ≥2B language model does not fit a 512 MB Tier-0 host, and that perceptual identity (speaker recognition and face recognition) is present at Tier 2 and above when enabled, and absent at Tier 0 and Tier 1 (identity models not provisioned at those tiers).

#### Scenario: Capability matrix includes perceptual identity row
- **WHEN** the capability matrix is published
- **THEN** it SHALL include a row for perceptual identity stating: present at Tier 2 (workstation) and Tier 3 (datacenter) when enabled, absent at Tier 0 (edge) and Tier 1 (embodied CPU)

#### Scenario: Identity models not provisioned below Tier 2
- **WHEN** the deployment tier is Tier 0 or Tier 1
- **THEN** the speaker embedding and face detection models SHALL NOT be provisioned, and the identity-binding configuration flags SHALL be forced to disabled regardless of operator configuration
