## ADDED Requirements

### Requirement: The probe names the tier selector
The host probe's help text and its printed recommendation SHALL tell the
operator to apply the recommended tier with `KAINE_TIER` (or
`[deployment].tier` in the operator configuration). They SHALL NOT suggest
`KAINE_PROFILE` or `--profile`, which select a module profile and do not apply
a tier.

#### Scenario: The printed advice names KAINE_TIER
- **WHEN** the probe prints a Tier 1 recommendation as text
- **THEN** the output contains `KAINE_TIER=tier1` and does not contain
  `KAINE_PROFILE`
