## ADDED Requirements

### Requirement: Renderings never format a latent field
Every renderer that turns an event into text for the organ's prompt or for a log (`FaithfulRenderer.render_event`, `redact_heard_speech`, the felt renderer and its heard redaction) SHALL remove every `LATENT_FIELDS` key from the payload with `strip_latent()` before any template or fallback runs. The intent log's `numeric_rendering` and the organ's prompt SHALL hold no number taken from a latent field.

#### Scenario: Felt mode, the numeric sidecar
- **WHEN** `awareness_rendering = "felt"` and the coalition holds an `audition.perception` carrying `latent` and `latent_derived`
- **THEN** the intent log's `numeric_rendering` holds none of their numbers

#### Scenario: Numeric mode, the prompt
- **WHEN** `awareness_rendering = "numeric"` and the coalition holds the same event
- **THEN** the prompt sent to the organ holds none of their numbers

#### Scenario: A template-less event
- **WHEN** an event with no template carries a `latent_derived` mapping and other scalar fields
- **THEN** the fallback rendering names the scalar fields and holds no number from the mapping

### Requirement: audition.perception has a numeric template
The numeric template set SHALL have a template for `("audition", "audition.perception")` that reads its declared scalar fields only, so the event never falls through to the generic fallback that formats every payload key.

#### Scenario: The numeric rendering of an acoustic report
- **WHEN** an `audition.perception` report is rendered numerically
- **THEN** the text comes from its own template and names only its declared scalar fields
