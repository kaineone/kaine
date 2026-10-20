## ADDED Requirements

### Requirement: Tier-1 regulation bias on one source's scores
When `[workspace].regulation_bias` is true, the workspace SHALL read each tier-1 `affect.regulation` event among a tick's candidates and multiply the score `S'` of every candidate of the named source by `1 - b`, with `b = bias × exp(-(t - t1) / decay_s)` and `t1` the entity time the cycle collected the event, until a later tier-1 event replaces it. The factor SHALL lie in `[1 - bias, 1]`. Ticks with an active bias SHALL record `regulation_bias` (source and factor) in the broadcast metadata. With no tier-1 event, or with `regulation_bias` false, scores and metadata SHALL be bit-for-bit those without the layer. This is the only per-source factor affect applies to selection.

#### Scenario: The bias lowers the target and decays
- **WHEN** a tier-1 event names `vision` with bias 0.2 and decay 20 s
- **THEN** a vision candidate's score is multiplied by 0.8 on the next tick and by `1 - 0.2 e^-1` 20 entity seconds later, and other sources are unchanged

#### Scenario: No bias in the study arms
- **WHEN** any `config/studies/workspace_mediation_*.toml` is loaded
- **THEN** `[workspace].regulation_bias` is false, and a tick with a tier-1 event ranks candidates by `I × N` exactly as without it
