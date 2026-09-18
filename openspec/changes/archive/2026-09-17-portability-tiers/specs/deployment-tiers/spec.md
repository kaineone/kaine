## ADDED Requirements

### Requirement: Named tier profiles select a coherent deployment for a host class

The system SHALL ship named tier profiles (Tier 0 edge/sensor node, Tier 1
embodied CPU agent, Tier 2 workstation, Tier 3 datacenter) as configuration
overlays that set module toggles, runtime-backend selections, device hints, and
cycle-rate hints appropriate to a host class. A profile SHALL be applied as a
layer between the shipped defaults and the operator's local working config, so
that local operator overrides still win.

Tier 2 SHALL be the default and SHALL be behavior-identical to the current
workstation deployment.

#### Scenario: Selecting a profile layers it under local overrides

- **WHEN** the operator selects a profile via `KAINE_PROFILE` or `--profile`
- **THEN** the profile's toggles, backends, and hints are applied over the
  shipped defaults
- **AND** any value also set in the local working `config/kaine.toml` overrides
  the profile

#### Scenario: No profile means Tier 2

- **WHEN** no profile is selected
- **THEN** the system behaves identically to the current workstation default

### Requirement: Tier profiles preserve the safety invariants

A tier profile SHALL NOT enable the entity automatically and SHALL NOT embed the
private predefined voice. Enabling modules and selecting a private voice remain
local-config operator actions, exactly as for the shipped `kaine.toml`.

#### Scenario: Shipped profiles are inert and voice-free

- **WHEN** any shipped tier profile is loaded on its own
- **THEN** it does not auto-start the entity beyond the operator-supervised boot
- **AND** it contains no private predefined-voice identifier

### Requirement: Each tier publishes an honest capability statement

The system documentation SHALL include a capability matrix stating, per tier,
which faculties are present, degraded, or absent — including that vocal-emotion
and expressive TTS are absent below Tier 2, that vision is periodic (not
streaming) at Tier 1, and that a ≥2B language model does not fit a 512 MB
Tier-0 host.

#### Scenario: Capability matrix names what a tier cannot do

- **WHEN** the deployment documentation is consulted for a tier
- **THEN** it states both the faculties that tier provides and the faculties it
  lacks or degrades
