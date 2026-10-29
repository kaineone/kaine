## ADDED Requirements

### Requirement: Awake fatigue builds with the housekeeping pressure
While awake, the fatigue accumulator SHALL build at `e (1 + P^hk)`, where `e` is its existing input and `P^hk` the housekeeping pressure (paper A.5); the pressure SHALL have no ceiling. Asleep, or when the pressure is 0, unreadable or not a finite number at least 0, the accumulator SHALL behave exactly as before.

#### Scenario: A resource at twice its budget
- **WHEN** the pressure is 1.0 and the entity is awake
- **THEN** fatigue builds twice as fast as with no pressure

#### Scenario: Asleep
- **WHEN** the pressure is 1.0 and the entity sleeps
- **THEN** fatigue changes exactly as it would with no pressure
