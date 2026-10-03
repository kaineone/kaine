## ADDED Requirements

### Requirement: A study records the workspace graph, not every module's output
`build_overlay` SHALL set `[research_event_log.nexus_record].enabled = false` and `[evaluation].workspace_trajectory = false` for every study step, overriding any operator setting, and SHALL keep `[ignition_log].enabled = true`. Run-control and safety records (gestation readouts and viability, preservation and welfare monitors, research events, external utterances, the evaluation instruments) SHALL be unaffected.

#### Scenario: An operator config enables the Nexus record
- **WHEN** the operator config sets `[research_event_log.nexus_record].enabled = true` and `[evaluation].workspace_trajectory = true`
- **THEN** every step's overlay sets both to false and the ignition log stays enabled

#### Scenario: Safety records are kept
- **WHEN** an overlay is built for a gestation step
- **THEN** it still enables the ignition log, the research event log, external utterances and the preservation monitors
