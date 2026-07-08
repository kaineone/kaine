# topos

## MODIFIED Requirements

### Requirement: Report carries peripheral and foveal latents under foveation

When foveation is enabled, the `topos.report` SHALL carry a peripheral latent and a
foveal latent, each tagged by role, together with the content-free fovea location
`(x, y, size)`, in place of a single whole-frame latent. When foveation is disabled
the report SHALL carry the single whole-frame latent exactly as before. In both
cases the DINOv2/clip encoder SHALL remain frozen (no gradients flow into it) and no
raw imagery SHALL be written to disk.

#### Scenario: Foveated report shape

- **WHEN** Topos publishes a report with foveation enabled
- **THEN** the payload carries a `peripheral` latent, a `foveal` latent, and the
  normalized fovea location and size, and carries no pixel data

#### Scenario: Non-foveated report unchanged

- **WHEN** Topos publishes a report with foveation disabled
- **THEN** the payload carries the single whole-frame latent exactly as before this
  change

#### Scenario: Encoder stays frozen under foveation

- **WHEN** the peripheral and foveal views are encoded
- **THEN** no parameter of the encoder is modified
