## MODIFIED Requirements

### Requirement: Thesis-test module set

The system SHALL provide an opt-in run configuration that enables exactly the base-thesis module set:
- the diverse predictive processors: Soma, Chronos, Topos and Audition;
- Thymos, the affective precision core;
- Hypnos, fatigue-triggered sleep, with voice alignment off;
- Lingua, the output-only voice;
- the always-on Syneidesis and Volition.

Every other module (Mnemos, Eidolon, Phantasia, Empatheia, Nous, Vox, Praxis, Perception, Mundus, Echo) SHALL remain built and disabled. The configuration SHALL NOT remove or delete any module.

The profile `config/profiles/thesis_test.toml` SHALL be the single definition of this set. The operator overlay carries host-local values and deliberate deviations, and the first-run wizard's base-thesis preset reads the profile.

#### Scenario: Only the thesis processors activate

- **WHEN** the thesis-test configuration is selected at boot
- **THEN** exactly Soma, Chronos, Topos, Audition, Thymos, Hypnos and Lingua are registered, Syneidesis and Volition run as scaffolding, and every other module is disabled but present

#### Scenario: The wizard's base-thesis preset matches the profile

- **WHEN** the first-run wizard offers the base-thesis preset
- **THEN** its module choices equal the profile's enabled set
