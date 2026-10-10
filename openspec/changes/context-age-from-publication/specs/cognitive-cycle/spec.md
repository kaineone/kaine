## ADDED Requirements

### Requirement: Context age is entity time since publication
Each workspace broadcast SHALL carry its publication time on the entity clock, and a module's broadcast context SHALL report its age as the entity time elapsed since that publication, falling back to the time of receipt only when the broadcast carries no publication time, and never negative. Every module that keeps a broadcast context SHALL measure it on the shared entity clock.

#### Scenario: Age counts from publication
- **WHEN** a broadcast published at entity time 10.0 is adopted and the module forms a prediction at entity time 12.5
- **THEN** the context age is 2.5 seconds

#### Scenario: Audition uses the entity clock
- **WHEN** Audition is built at boot
- **THEN** its broadcast context measures age on the shared entity clock
