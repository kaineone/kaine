## ADDED Requirements

### Requirement: A leading drive event yields a stir in the developmental phase
While the entity is developing, an accessed broadcast whose first non-organ member is its own boredom or restlessness drive event SHALL yield an `intent.stir` instead of any other intent, when at least `refractory_s` (default 300) of entity time have passed since the last stir. No other intent SHALL be emitted for that broadcast; other broadcasts SHALL yield intents as before. After maturation no stir SHALL be emitted. The code site SHALL mark the trigger as a design choice.

#### Scenario: Boredom leads an accessed broadcast
- **WHEN** a developing entity's boredom drive event is the first member of an accessed broadcast and no stir came in the last 300 s
- **THEN** one `intent.stir` is published and no speak or think intent

#### Scenario: Within the refractory period
- **WHEN** the same happens 120 s after the last stir
- **THEN** no stir is published

#### Scenario: Speech in the developmental phase is unchanged
- **WHEN** a developing entity's accessed broadcast is led by a vision report scoring above the speak bar
- **THEN** a speak intent is emitted as before

#### Scenario: After maturation
- **WHEN** a matured entity's boredom drive event leads an accessed broadcast
- **THEN** no stir is published and the usual rules apply
