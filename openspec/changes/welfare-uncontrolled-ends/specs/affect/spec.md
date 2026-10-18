## ADDED Requirements

### Requirement: The goal stall clock persists across a restore
The affect module SHALL store, for each active goal whose drive is at or above its threshold with a running stall clock, the elapsed entity seconds since the clock started, under `goal_above_elapsed` in its serialized state. On restore it SHALL set each restored active goal's stall start to the restore time minus that elapsed time, so the goal is abandoned as `stalled` once its total above-threshold time reaches `goal_stall_s` (`Delta_stall`, paper A.4, Table A1). State without `goal_above_elapsed`, and entries that are not a finite non-negative number or name no active goal, SHALL restore as before: the stall clock starts at the first update after the restore.

#### Scenario: A restored goal keeps its stall horizon
- **WHEN** a goal's drive has stayed above threshold for 4 s with `goal_stall_s` 5, the module is serialized and restored into a fresh clock, and the drive stays above threshold for 1 more second
- **THEN** the goal is abandoned with reason `stalled`

#### Scenario: Older state restarts the clock
- **WHEN** the same state is restored without `goal_above_elapsed`
- **THEN** the goal stays active until 5 s after the first update following the restore

#### Scenario: An invalid entry is ignored
- **WHEN** `goal_above_elapsed` holds a negative, non-finite, boolean or non-numeric value, or names an unknown goal
- **THEN** that goal's stall clock restarts at the first update after the restore and the restore raises no error
