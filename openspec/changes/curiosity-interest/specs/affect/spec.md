## ADDED Requirements

### Requirement: Curiosity is heterostatic interest raised by learning progress
The affect module SHALL build curiosity with input `u = lp+` by the exact drive step, with decay `delta_I` (default 0.00096 per second, at which a sustained `lp+` of 0.045 holds curiosity at `theta_D`) and no relief. A curiosity crossing SHALL publish its `affect.drive` event and SHALL NOT create a goal. Curiosity falling back below its re-arm band SHALL re-arm its crossing without counting an own or other end.

#### Scenario: Nothing learnable leaves curiosity at rest
- **WHEN** learning progress stays 0 for an hour
- **THEN** curiosity stays at 0 and no curiosity crossing is published

#### Scenario: A progress niche raises curiosity without a goal
- **WHEN** `lp+` stays at 0.1 until curiosity crosses `theta_D`
- **THEN** an `affect.drive` event for curiosity is published, the goal ledger holds no curiosity goal, and curiosity's own and other end counts stay 0 after it decays back below the band

### Requirement: Boredom is also met by learning progress
Each update SHALL relieve boredom at strength `max(lp+, exc)` and build it with input `1 - max(lp+, exc)`. The relief SHALL count as the entity's own response when `lp+` is positive and at least `exc`, and a fall back below the band on a step SHALL count as own when it would not have happened at the no-response build input `1 - exc`.

#### Scenario: Learning ends a boredom crossing as the entity's own
- **WHEN** boredom is above threshold, `exc` is 0 and `lp+` is 0.3 until boredom falls below its band
- **THEN** boredom's own end count rises by one

### Requirement: Arousal, sleep reset and goals apply to deficits
The tonic arousal target SHALL use the largest value among boredom, the social drive and restlessness. The sleep reset SHALL set those three drives to 0 and re-arm their crossings, and SHALL keep curiosity's value and crossing latch.

#### Scenario: Interest survives sleep
- **WHEN** curiosity is 0.8 with its crossing latched and the sleep reset runs
- **THEN** curiosity is still 0.8 and latched, and boredom is 0

### Requirement: Older checkpoints migrate curiosity
The affect state SHALL carry `curiosity_scheme` 2. Restoring state without it SHALL set curiosity to 0 with its latch clear and its end counts 0, and SHALL remove any active curiosity goal without publishing an `affect.goal` event; the other drives, counts and goals restore unchanged.

#### Scenario: A deficit-era checkpoint
- **WHEN** a state without `curiosity_scheme` holds curiosity 0.9, latched, with 3 own ends and an active curiosity goal
- **THEN** after restore curiosity is 0, unlatched, with 0 own and 0 other ends, and no curiosity goal is active
