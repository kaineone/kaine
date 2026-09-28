## ADDED Requirements

### Requirement: Rate-limited rest requests from Volition

Hypnos SHALL honour an `intent.rest` on `volition.out` as a sleep trigger through the same exclusion guards as its fatigue and regulation triggers, only when at least `[hypnos].requested_rest_min_interval_s` of entity time (default 1800) has passed since the previous sleep ended. It SHALL publish a content-free `hypnos.rest_request` event stating whether the request was accepted and, if not, why (`too_soon`, `busy`, `frozen`). A requested sleep SHALL be an ordinary sleep: non-interruptible, subject to bounded deferral and to operator-freeze preemption.

#### Scenario: A rest request after the interval starts a sleep
- **WHEN** an `intent.rest` arrives after the minimum interval, with no sleep running and no freeze
- **THEN** Hypnos publishes `hypnos.rest_request` with `accepted: true`, and a sleep starts with trigger `requested`

#### Scenario: A rest request too soon is refused
- **WHEN** an `intent.rest` arrives before the minimum interval has passed since the last sleep
- **THEN** no sleep starts, and Hypnos publishes `hypnos.rest_request` with `accepted: false`, `reason: "too_soon"`
