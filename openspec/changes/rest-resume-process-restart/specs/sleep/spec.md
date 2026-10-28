## MODIFIED Requirements

### Requirement: The state cycle survives a restart
The sleep module SHALL persist the state cycle's phase and the entity time spent in it, in the resume checkpoint and across an in-process restart alike. After a restart during awake time the next rest SHALL come when the awake time already spent plus the new awake time reaches `T_act`. After a restart during a rest, including a restart of the process, the rest SHALL resume for its remaining time and then end as any rest does. While a rest runs, the checkpoint's sleep `state_cycle` entry SHALL be brought up to date when the rest starts, after every 60 s of rest, at a shutdown during the rest and when the rest ends, so a crash loses at most 60 s of rest and a crash after a rest resumes none.

#### Scenario: A restart during a rest
- **WHEN** the cycle is restarted 600 s into a 1410 s rest
- **THEN** after the restart the entity rests for the remaining 810 s and the next awake period then begins

#### Scenario: A process restart during a rest
- **WHEN** the process is stopped 710 s into a 1410 s rest and a new process starts on the same state tree
- **THEN** the new process resumes the rest for the remaining 700 s and the maturation gate counts the cut rest and its resumption as one sleep cycle

#### Scenario: A crash during a rest
- **WHEN** the process dies 710 s into a rest with no clean shutdown
- **THEN** the new process resumes the rest from the last 60 s mark, losing at most 60 s of rest

#### Scenario: A crash just after a rest
- **WHEN** the process dies after a rest ended and before the next full checkpoint
- **THEN** the new process resumes no rest
