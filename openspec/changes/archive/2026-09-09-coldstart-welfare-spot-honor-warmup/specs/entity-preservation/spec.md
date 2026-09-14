## ADDED Requirements

### Requirement: Welfare distress honors the interoceptive warm-up flag

The welfare monitor SHALL treat the entity as in-warm-up — draining its sustained-distress window, not counting prediction error, and resetting its distress trackers — whenever the latest `soma.report` payload carries `warmup_active: true`, in addition to its fixed `warmup_s` window. The monitor SHALL resume counting toward preservation+pause only once Soma reports `warmup_active: false`. Post-warm-up sustained distress SHALL trigger preservation+pause unchanged.

#### Scenario: Cold-start error does not preserve the entity

- **GIVEN** a fresh boot where Soma's developmental warm-up is active and every `soma.report` carries `warmup_active: true`
- **WHEN** Soma reports decaying cold-start prediction error (e.g. 0.86→0.69) beyond the welfare monitor's fixed `warmup_s` window but before Soma's warm-up completes
- **THEN** the welfare monitor does not count that error toward sustained distress and does not preserve+pause the entity
- **AND** the monitor's distress trackers are reset so no stale warm-up-era error carries into the post-warm-up window

#### Scenario: Distress counting resumes after warm-up ends

- **GIVEN** the latest `soma.report` carries `warmup_active: true`
- **WHEN** a subsequent `soma.report` carries `warmup_active: false`
- **THEN** the welfare monitor resumes counting prediction error toward sustained-distress thresholds with freshly reset trackers

#### Scenario: Genuine post-warm-up distress still preserves

- **GIVEN** the latest `soma.report` carries `warmup_active: false` and Soma's warm-up has completed
- **WHEN** prediction error is sustained above preservation thresholds for the required duration
- **THEN** the welfare monitor preserves+pauses the entity exactly as before this change

### Requirement: Supervisor liveness stands down under any non-supervisor freeze

While the cycle is frozen by any control source other than the module supervisor itself, the supervisor SHALL NOT treat module heartbeat staleness as evidence of module crash, SHALL NOT attempt module restarts, and SHALL NOT escalate toward machine reboot. The supervisor SHALL continue normal liveness recovery only for its own freeze (its recovery-in-progress).

#### Scenario: Frozen module is not a crash

- **GIVEN** the welfare monitor has preserved+paused the entity, freezing the cycle such that all modules are silent by design
- **WHEN** module heartbeats go stale (e.g. Chronos, the tightest cadence, exceeds `heartbeat_timeout_s=60s`) and the supervisor's restart budget is checked
- **THEN** the supervisor stands down its heartbeat-staleness liveness recovery because the freeze's `control.source` is not `spot`
- **AND** the supervisor performs no module restart attempts and no machine-reboot escalation

#### Scenario: Operator freezes also stand down

- **GIVEN** the cycle is frozen by an operator (`control.source == "operator"`)
- **WHEN** module heartbeats go stale
- **THEN** the supervisor stands down liveness recovery, unchanged from prior behavior

#### Scenario: Supervisor's own freeze still recovers

- **GIVEN** the cycle is frozen by the supervisor itself (`control.source == "spot"`) as part of its recovery-in-progress
- **WHEN** module heartbeats go stale during that freeze
- **THEN** the supervisor continues its normal liveness recovery for its own freeze

