## ADDED Requirements

### Requirement: The live oscillatory ablation is switched by configuration
`EvaluationConfig` SHALL read `[evaluation].oscillatory_ablation` (boolean, default `false`). When it is `true`, the sidecar SHALL build the ablation recorder and the cycle SHALL attach it; when it is absent or `false`, no recorder is built and the cycle takes its plain selection path.

#### Scenario: Enabling the ablation from configuration
- **WHEN** `[evaluation].oscillatory_ablation = true`
- **THEN** the sidecar registry exposes an ablation recorder for the cycle to attach
