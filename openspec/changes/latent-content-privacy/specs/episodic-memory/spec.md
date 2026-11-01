## ADDED Requirements

### Requirement: The store-time rules run in a fixed order
Before storing a trace, the episodic memory module SHALL apply three rules to each coalition member, in this order: the shared heard rule (a heard member is stored by source and type with no payload); the raw-perceptual omit (`embodiment.visual.raw` is stored by source and type with no payload); and the latent rule (every other payload passes `strip_vectors`). The episodic memory module SHALL NOT be enabled in any entity before the store applies the shared heard rule (merged in #636).

#### Scenario: A heard member is removed whole
- **WHEN** a coalition member is an `embodiment.chat` event that also carries a `latent_derived` mapping
- **THEN** the trace stores that member by source and type only, marked as heard

#### Scenario: A raw member keeps its marker
- **WHEN** a coalition member is an `embodiment.visual.raw` event
- **THEN** the trace stores it with `<raw-perceptual omitted>` and no payload

### Requirement: Stored traces hold no latent value outside the identity-bound field
No stored trace text, trace payload, replay event or recall event SHALL hold a key in `LATENT_FIELDS` (`latent_derived` included) or a value that was held under one, at any depth, with the one exception of the identity-bound field of the next requirement.

#### Scenario: A member carrying a latent-derived mapping
- **WHEN** a broadcast's coalition holds a vision report with `latent`, `latent_derived` and `change_score`
- **THEN** the stored trace keeps `change_score` and holds neither `latent` nor `latent_derived`

#### Scenario: A short latent-derived vector is not stored
- **WHEN** a member's `latent_derived` mapping holds a list of 8 numbers
- **THEN** none of those numbers appears in the stored trace text or payload

### Requirement: A content code may be stored only as identity-bound content
Under the ruling on `latent-content-privacy` design open question 2 (option b, 2026-11-01), a trace MAY hold one content code, only in its field `latent_derived.identity_bound.code`, with the code's id and generation. The code SHALL NOT appear in embedded or rendered trace text, recall or replay text, a persisted bus stream, a log, a research record, the intent log, or the organ's corpus or prompt. Until a reviewed component writes the field, no trace SHALL hold one.

#### Scenario: The trace text
- **WHEN** a trace with an identity-bound code is rendered for recall
- **THEN** the rendered text holds no number from the code

### Requirement: Identity-bound content is encrypted and bound to its code
The store SHALL refuse to write an identity-bound code unless state encryption is in effect and the store's files are encrypted at rest. Recall SHALL ignore a stored code whose code id differs from the running content code's. The preservation capture SHALL carry the field as part of the store, and decommission SHALL remove it with the store.

#### Scenario: Encryption is off
- **WHEN** a writer asks the store to keep a content code with state encryption off
- **THEN** the store refuses and stores the trace without the field

#### Scenario: A code from another life
- **WHEN** a merged entity's store holds a trace whose code id is the other parent's
- **THEN** recall ignores that trace's code and uses the trace's other fields
