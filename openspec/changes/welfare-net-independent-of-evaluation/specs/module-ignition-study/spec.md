## MODIFIED Requirements

### Requirement: A study records the workspace graph, not every module's output
`build_overlay` SHALL set `[research_event_log.nexus_record].enabled = false`, `[evaluation].workspace_trajectory = false` and `[evaluation].enabled = false` for every study step, overriding any operator setting, and SHALL keep `[ignition_log].enabled = true`. No evaluation observer SHALL run in a study. Run-control and safety records (gestation readouts and viability, preservation and welfare monitors including the gray-zone producer, research events, external utterances, the run manifest) SHALL be unaffected.

#### Scenario: An operator config enables the Nexus record
- **WHEN** the operator config sets `[research_event_log.nexus_record].enabled = true` and `[evaluation].workspace_trajectory = true`
- **THEN** every step's overlay sets both to false and the ignition log stays enabled

#### Scenario: Safety records are kept
- **WHEN** an overlay is built for a gestation step
- **THEN** it still enables the ignition log, the research event log, external utterances and the preservation monitors

#### Scenario: Evaluation observers are off in a study
- **WHEN** the operator config sets `[evaluation].enabled = true`
- **THEN** every step's overlay sets `[evaluation].enabled = false`
