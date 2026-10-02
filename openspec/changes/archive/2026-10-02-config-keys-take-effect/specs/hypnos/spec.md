## ADDED Requirements

### Requirement: The rest interval Hypnos enforces is the configured one
The composition root SHALL pass `[hypnos].requested_rest_min_interval_s` to Hypnos, so the interval Hypnos uses for its own `too_soon` decision is the same value Volition's rest proposals use. A value that is not a number greater than 0 SHALL be a configuration error at boot.

#### Scenario: A non-default interval is honoured
- **WHEN** `[hypnos].requested_rest_min_interval_s = 600` and a rest request arrives 900 s of entity time after the previous sleep ended
- **THEN** Hypnos accepts it, where the 1800 s default would have refused it as `too_soon`

#### Scenario: An invalid interval refuses boot
- **WHEN** `[hypnos].requested_rest_min_interval_s = 0`
- **THEN** building Hypnos raises a configuration error naming the key
