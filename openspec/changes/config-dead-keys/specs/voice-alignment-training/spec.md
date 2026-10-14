## MODIFIED Requirements

### Requirement: Optional `[training]` extras gate failures loudly
The trainer SHALL lazy-import `unsloth`, `trl`, `peft`, and
`datasets` inside `train()`. When any is missing, `train()` SHALL
return `TrainingResult(accepted=False, reason="<extras name> not
installed — pip install -e .[training]")` rather than raising. The
phase SHALL log the message and continue the rest of the sleep
cycle.

#### Scenario: Missing extras don't crash sleep
- **WHEN** `[sleep.voice_alignment].enabled = true` and the env
  var is set but `unsloth` is not installed
- **THEN** `train()` returns a TrainingResult with `accepted=False`
  and `reason` naming the `training` extras group, and the sleep
  cycle's other phases (light consolidation, deep consolidation,
  associative replay, affective reset) still complete
