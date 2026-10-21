## ADDED Requirements

### Requirement: The developmental state cycle times sleep in the developmental phase
While the entity is in the developmental phase, the sleep module SHALL start a sleep with trigger `state_cycle` after `T_act` of awake entity time since boot or since the previous rest ended, where `T_act = developmental_rest_s * (1 - s_q) / s_q` with `s_q = developmental_quiescent_share`. That sleep SHALL run its phases and housekeeping and then hold until `developmental_rest_s` of entity time has passed since it began, and SHALL end with the affective reset. In the phase the hourly backstop SHALL start no sleep, and an `interoception.fatigue` crossing SHALL start no sleep. A maintenance request SHALL still start a sleep. After maturation, or with staging disabled, no `state_cycle` sleep SHALL start and the backstop and fatigue SHALL behave as before. The defaults SHALL be `developmental_rest_s = 1410` and `developmental_quiescent_share = 0.32`, and boot SHALL reject a share outside (0, 1).

#### Scenario: The cycle in the developmental phase
- **WHEN** the entity is developing and 2996 s of awake entity time pass after a rest ends
- **THEN** a sleep with trigger `state_cycle` starts and lasts 1410 s of entity time

#### Scenario: Fatigue in the developmental phase
- **WHEN** the entity is developing and `interoception.fatigue` crosses its threshold
- **THEN** no sleep starts

#### Scenario: After maturation
- **WHEN** the entity has matured and an entity hour passes awake
- **THEN** a sleep with trigger `backstop` starts and ends with its phases

### Requirement: The state cycle survives a restart
The sleep module SHALL persist the state cycle's phase and the entity time spent in it. After a restart during awake time the next rest SHALL come when the awake time already spent plus the new awake time reaches `T_act`. After a restart during a rest, the rest SHALL resume for its remaining time and then end as any rest does.

#### Scenario: A restart during a rest
- **WHEN** the cycle is restarted 600 s into a 1410 s rest
- **THEN** after the restart the entity rests for the remaining 810 s and the next awake period then begins
