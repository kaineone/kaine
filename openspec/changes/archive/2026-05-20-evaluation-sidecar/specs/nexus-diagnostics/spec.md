## ADDED Requirements

### Requirement: Diagnostics gains an evaluation sub-route
The Nexus diagnostics surface SHALL expose
`/diagnostics/evaluation` returning a rendered HTML page with the
sidecar's aggregated metrics: A/B divergence rate over time, voice
alignment similarity over sleep cycles, module contribution
histogram, proactive output frequency, sleep before/after table,
Eidolon self-model accuracy, affect-output correlation matrix.

#### Scenario: Route exists when sidecar enabled
- **WHEN** `[evaluation].enabled = true` and Nexus is built
- **THEN** GET `/diagnostics/evaluation` returns 200

#### Scenario: Route absent when sidecar disabled
- **WHEN** `[evaluation].enabled = false`
- **THEN** GET `/diagnostics/evaluation` returns 404
