## ADDED Requirements

### Requirement: The remaining cognitive timers run on the entity clock
Chronos's interval and time-since-interaction measures, the Volition speak guard, the drive policy's timing and Vox's prosody-mirroring decay SHALL derive their durations and "now" from the shared `EntityClock`. Soma's cycle-latency sense SHALL compare the tick's subjective duration (its wall duration multiplied by the clock's `time_scale`) with its setpoint. Sites that track real audio or media, bound a real compute or network budget, or stamp records SHALL stay on wall time and SHALL be marked as such in the code.

#### Scenario: Dilation moves every cognitive timer together
- **WHEN** `time_scale = 0.5` and one wall second passes
- **THEN** Chronos's interval feature, the Volition speak guard, the drive policy and Vox's mirroring decay each advance by half a subjective second

#### Scenario: A dilated mind does not feel its slow hardware
- **WHEN** a tick takes 300 ms of wall time at `time_scale = 0.5`
- **THEN** Soma's cycle-latency sense receives 150 ms

#### Scenario: The default is unchanged
- **WHEN** `time_scale = 1.0`
- **THEN** every timer named here computes the same values as before this change
