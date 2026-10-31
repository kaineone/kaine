## ADDED Requirements

### Requirement: The store-time rules run in a fixed order
Before storing a trace, the episodic memory module SHALL apply three rules to each coalition member, in this order: the shared heard rule (a heard member is stored by source and type with no payload); the raw-perceptual omit (`embodiment.visual.raw` is stored by source and type with no payload); and the latent rule (every other payload passes `strip_vectors`). The episodic memory module SHALL NOT be enabled in any entity before the store applies the shared heard rule.

#### Scenario: A heard member is removed whole
- **WHEN** a coalition member is an `embodiment.chat` event that also carries a `latent_derived` mapping
- **THEN** the trace stores that member by source and type only, marked as heard

#### Scenario: A raw member keeps its marker
- **WHEN** a coalition member is an `embodiment.visual.raw` event
- **THEN** the trace stores it with `<raw-perceptual omitted>` and no payload

### Requirement: Stored traces hold no latent value
No stored trace text, trace payload, replay event or recall event SHALL hold a key in `LATENT_FIELDS` (`latent_derived` included) or a value that was held under one, at any depth.

#### Scenario: A member carrying a latent-derived mapping
- **WHEN** a broadcast's coalition holds a vision report with `latent`, `latent_derived` and `change_score`
- **THEN** the stored trace keeps `change_score` and holds neither `latent` nor `latent_derived`

#### Scenario: A short latent-derived vector is not stored
- **WHEN** a member's `latent_derived` mapping holds a list of 8 numbers
- **THEN** none of those numbers appears in the stored trace text or payload
