## ADDED Requirements

### Requirement: Voice alignment runs only on pre-registered steps
`init` SHALL record `voice_alignment_steps` in the study plan: a list of `{line, k}` steps. It defaults to the final accumulate step only (`{"line": "accumulate", "k": len(order)}`), and the operator can set it explicitly at `init`. The plan SHALL reject unknown lines and out-of-range steps.

`build_overlay` SHALL set `[hypnos.voice_alignment].enabled = true` for exactly those steps and `false` for every other step, overriding any operator setting, so the choice is fixed before launch and recorded in each step's overlay hash. A step with voice alignment enabled SHALL still require the operator approval variable in its environment. Without it, voice alignment stays off by the existing two-layer opt-in, and the step records that.

#### Scenario: Default is the final accumulate step
- **WHEN** a study is initialised with nine modules in `order` and no explicit `voice_alignment_steps`
- **THEN** the plan records `[{"line": "accumulate", "k": 9}]`

#### Scenario: Only the registered step enables voice alignment
- **WHEN** overlays are built for every step of that study
- **THEN** `accumulate` step 9 has `[hypnos.voice_alignment].enabled = true`, and every other step has it `false`, even when the operator configuration enables it

#### Scenario: An invalid registration is refused
- **WHEN** `voice_alignment_steps` names an unknown line or a step outside that line's range
- **THEN** `init` refuses with an error naming the entry
