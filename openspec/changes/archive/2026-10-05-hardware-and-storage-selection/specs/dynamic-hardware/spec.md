## ADDED Requirements

### Requirement: Runtime device resolution stays within the allowed set
When `[hardware].allowed_devices` is present, `resolve_device` SHALL NOT return a device outside that set. A request for a device outside the set SHALL fall back within the allowed set with a warning, or to CPU when the set holds no accelerator. `KAINE_FORCE_DEVICE` SHALL still override, and it SHALL be logged as an override of the operator's allowed set. When `[hardware]` is absent, resolution SHALL be unchanged.

#### Scenario: A module asks for an excluded GPU
- **WHEN** a module's configured device is a GPU outside the allowed set
- **THEN** it resolves to a device inside the allowed set
- **AND** a warning names both devices

#### Scenario: No hardware section
- **WHEN** the operator config has no `[hardware]` section
- **THEN** device resolution behaves as it did before this change
