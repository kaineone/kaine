## ADDED Requirements

### Requirement: The awake floor reports a missing volume once per change
The awake floor SHALL log a missing watched volume once, and again only after the volume's presence changes. It SHALL go on skipping a missing volume as before.

#### Scenario: A sink that never exists
- **WHEN** a configured sink directory stays missing across many floor checks
- **THEN** the floor logs one warning for it
