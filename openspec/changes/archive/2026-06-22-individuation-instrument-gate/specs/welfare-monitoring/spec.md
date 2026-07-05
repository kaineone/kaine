## ADDED Requirements

### Requirement: The welfare-protective monitor applies a boot cold-start warm-up

The cycle-layer welfare-protective monitor SHALL apply a configured cold-start
warm-up (`[preservation.welfare_response].warmup_s`) after the run starts. During
the warm-up window, `welfare.gray_zone` and sustained-distress events SHALL be
observed and logged but SHALL NOT count toward the windowed-repeat threshold or
trigger the preserve-then-act response. This prevents boot transients — distress
reported before homeostatic setpoints settle — from being mistaken for sustained
welfare problems. After the warm-up window, both the windowed-repeat arm and the
sustained-distress arm function unchanged; genuine sustained distress re-accrues
immediately once warm-up ends.

#### Scenario: Boot-transient distress within warm-up does not trigger a response

- **WHEN** gray-zone or distress events occur within the configured `warmup_s`
  after run start
- **THEN** they are logged but do not count toward the repeat threshold and no
  preserve-then-act response is taken

#### Scenario: Sustained distress after warm-up still triggers the response

- **WHEN** the warm-up window has elapsed and repeated gray-zone events cross the
  configured threshold within the window (or Soma reports sustained distress)
- **THEN** the monitor preserves the entity first, then takes the configured
  action, as before
