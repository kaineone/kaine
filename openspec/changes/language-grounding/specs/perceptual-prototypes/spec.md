## ADDED Requirements

### Requirement: Perceptual modules form prototypes from their latents without labels

When `[perception.prototypes].enabled` is true, the vision module, and the audition module when its encoder provides a latent, SHALL maintain an online prototype store over the encoder's latent. A latent within a prototype's acceptance radius SHALL update that prototype; any other latent SHALL start a new one. No label, category name or fixed prototype count SHALL be configured.

#### Scenario: A repeated scene matches its prototype

- **WHEN** the same clip is presented twice with other clips between
- **THEN** the second presentation's reports match the prototype formed in the first

#### Scenario: Nothing is configured as a category

- **WHEN** the prototype configuration is read
- **THEN** it contains no category names and no prototype count

### Requirement: The acceptance radius comes from the latent's own distances

The acceptance radius SHALL be computed from a configured quantile of nearest-neighbour distances among recent latents of the same encoder. Prototypes below a minimum count after a decay horizon SHALL be pruned, and prototypes whose centroids converge SHALL merge.

#### Scenario: Shuffled latents do not form stable prototypes

- **WHEN** the offline check runs the prototype layer on the study films and on the same latents in shuffled order
- **THEN** the films' assignments are more stable across two viewings than the shuffled control's, by the margin recorded in the validation record

### Requirement: Reports carry a prototype reference and no latent-derived vector

When prototypes are enabled, `vision.report` and the audition report SHALL carry `prototype_id`, `prototype_match`, `prototype_new`, `prototype_count` and `prototype_last_seen_s`. The workspace scorer SHALL NOT read these fields.

#### Scenario: Prototype fields present, scorer unchanged

- **WHEN** a vision report is published with prototypes enabled
- **THEN** it carries the five prototype fields, and the scorer's score for it equals the score with prototypes disabled

### Requirement: Prototype centroids persist as the entity's learned state and are never logged

Prototype centroids SHALL persist by default, encrypted at rest, in preservation bundles and in fork snapshots, and a fork SHALL start from its parent's prototypes. Centroids SHALL be listed among the privacy filter's vector fields and SHALL NOT appear in diagnostics, the research event log or the workspace graph log.

#### Scenario: A fork inherits prototypes

- **WHEN** an entity with prototypes is forked
- **THEN** the fork's prototype store equals the parent's at the fork point

#### Scenario: Centroids never reach diagnostics

- **WHEN** the diagnostics surface or the research event log records a vision report
- **THEN** no centroid or latent appears in the record
