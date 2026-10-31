## ADDED Requirements

### Requirement: A leading drive event yields a stir in the developmental phase
While the development probe reports the entity as developing, an accessed broadcast whose first member that is not the organ's own is the entity's boredom or restlessness drive event SHALL yield an `intent.stir` instead of any other intent, when at least `refractory_s` (default 300) of entity time have passed since the last stir. No other intent SHALL be emitted for that broadcast. After maturation no stir SHALL be emitted.

#### Scenario: Boredom leads an accessed broadcast
- **WHEN** a developing entity's boredom drive event is the first member of an accessed broadcast and no stir came in the last 300 s
- **THEN** one `intent.stir` is published and no speak or think intent

#### Scenario: Within the refractory period
- **WHEN** the same happens 120 s after the last stir
- **THEN** no stir is published

#### Scenario: After maturation
- **WHEN** a matured entity's boredom drive event leads an accessed broadcast
- **THEN** no stir is published and the usual rules apply
