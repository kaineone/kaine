## ADDED Requirements

### Requirement: Drive-relevant sources are declared by the modules
The goal factor's drive-to-source mapping SHALL be built from what each registered module declares in `relieves_drives`, plus the declared workspace scaffolding sources. It SHALL be injected into the scorer, so the workspace layer never imports a module. Every declared tag SHALL be one of the four Thymos drives.

#### Scenario: A module's declaration drives the mapping
- **WHEN** a registered module declares `relieves_drives = {"curiosity"}`
- **THEN** with curiosity dominant, an event from that module is weighted as drive-relevant

#### Scenario: An unknown drive tag is rejected
- **WHEN** a module declares a tag that is not a Thymos drive
- **THEN** building the mapping raises an error at boot
