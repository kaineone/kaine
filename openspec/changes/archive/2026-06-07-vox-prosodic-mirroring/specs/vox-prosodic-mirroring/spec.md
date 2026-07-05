## ADDED Requirements

### Requirement: Bounded prosodic mirroring on top of affect
Vox SHALL blend a bounded residual of the latest `audition.prosody` features
(librosa-derived numeric features: F0 summary, RMS energy, speaking rate)
into the affect-driven `ChatterboxParams`, controlled by `mirror_strength`
clamped to `mirror_ceiling`, with the affect-driven parameters remaining
primary. The blend SHALL be a pure function of the affect params, the speaker
prosody, and the strength. No parselmouth dependency SHALL be introduced; all
prosody features are sourced exclusively from the `audition.prosody` event
published by Audition.

#### Scenario: Mirroring nudges toward speaker prosody
- **WHEN** the speaker's speaking rate is faster than the affect-driven baseline
  and mirroring is enabled
- **THEN** the synthesized `speed_factor` moves toward the speaker's rate but not
  past it

#### Scenario: Mirror residual is bounded
- **WHEN** speaker prosody differs greatly from the affect baseline at maximum
  strength
- **THEN** the parameter change does not exceed `mirror_ceiling`

#### Scenario: No parselmouth is used
- **WHEN** Vox processes prosodic mirroring for any utterance
- **THEN** no parselmouth function or Praat call is invoked; all prosody
  features come from the `audition.prosody` payload

### Requirement: Graceful degradation, decay, and opt-out
Vox SHALL fall back to affect-only parameters when no `audition.prosody` has been
seen or when `[vox.mirroring].enabled` is false, and the mirror residual SHALL
decay over `decay_s` after the partner stops speaking.

#### Scenario: No prosody yields affect-only voice
- **WHEN** synthesis occurs before any `audition.prosody` event
- **THEN** the parameters equal the affect-only mapping output

#### Scenario: Mirror fades after silence
- **WHEN** `decay_s` elapses with no new `audition.prosody`
- **THEN** the mirror residual has decayed toward zero
